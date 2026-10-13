from datetime import date, datetime, timezone
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Account, Client, Employee, FiscalYear, JournalEntry
from sqlalchemy import or_
from ..permissions import can, permission_required
from ..services.accounting import D, account_balance, create_posted_entry, get_system_account, reverse_entry
from ..services.accounts import ensure_client_account, ensure_employee_account
from ..services.operations import is_cash_account
from ..services.audit import audit

bp=Blueprint("accounting",__name__,url_prefix="/accounting")

ACCOUNT_TYPE_LABELS={"asset":"أصول","liability":"خصوم","equity":"حقوق ملكية","revenue":"إيرادات","expense":"مصروفات","memo":"مذكرة"}

def _children_tree(accounts):
    by_parent={}
    for account in accounts:
        by_parent.setdefault(account.parent_id,[]).append(account)
    for values in by_parent.values():
        values.sort(key=lambda x:(x.code or ""))
    def build(parent_id=None, depth=0):
        result=[]
        for account in by_parent.get(parent_id,[]):
            children=build(account.id,depth+1)
            balance=sum((node["balance"] for node in children),0) if children else (account_balance(account.id) if not account.is_group else 0)
            result.append({"account":account,"depth":depth,"children":children,"balance":balance})
        return result
    return build(None)

def _account_references(account_id):
    """Return a human-readable direct reference that prevents safe deletion."""
    from ..models import Agent, Client, Employee, Expense, JournalLine, Settlement, Voucher
    checks=[
        (JournalLine, "account_id", "قيد محاسبي"),
        (Voucher, "from_account_id", "سند"),
        (Voucher, "to_account_id", "سند"),
        (Expense, "expense_account_id", "مصروف"),
        (Expense, "cash_account_id", "مصروف"),
        (Settlement, "source_account_id", "تسوية"),
        (Settlement, "target_account_id", "تسوية"),
        (Agent, "account_id", "وكيل"),
        (Client, "account_id", "عميل"),
        (Employee, "account_id", "حساب موظف"),
        (Employee, "cashbox_account_id", "صندوق موظف"),
        (Employee, "payroll_account_id", "مستحق راتب"),
    ]
    for model,column_name,label in checks:
        column=getattr(model,column_name)
        if db.session.query(model).filter(column==account_id).first():
            return label
    return None

def _next_code(parent):
    existing=[a.code for a in Account.query.filter(Account.parent_id==parent.id).all() if a.code]
    prefix=f"{parent.code}"
    nums=[]
    for code in existing:
        if code.startswith(prefix) and code[len(prefix):].isdigit():
            nums.append(int(code[len(prefix):]))
    width=max([len(code)-len(prefix) for code in existing if code.startswith(prefix) and code[len(prefix):].isdigit()] or [2])
    return f"{prefix}{(max(nums)+1 if nums else 1):0{width}d}"


def _account_descendant_ids(account_id):
    """Return descendants for the parent picker, tolerating existing corrupt loops."""
    children_by_parent = {}
    for child_id, parent_id in Account.query.with_entities(Account.id, Account.parent_id).all():
        children_by_parent.setdefault(parent_id, []).append(child_id)

    descendants = set()
    pending = list(children_by_parent.get(account_id, []))
    while pending:
        child_id = pending.pop()
        if child_id == account_id or child_id in descendants:
            continue
        descendants.add(child_id)
        pending.extend(children_by_parent.get(child_id, []))
    return descendants


def _would_create_account_cycle(account_id, proposed_parent_id):
    """Fail closed if the proposed parent is the account or has a cyclic ancestry."""
    visited = set()
    current_id = proposed_parent_id
    while current_id is not None:
        if current_id == account_id or current_id in visited:
            return True
        visited.add(current_id)
        current = db.session.get(Account, current_id)
        if current is None:
            return True
        current_id = current.parent_id
    return False


def _eligible_account_parents(account):
    excluded_ids = _account_descendant_ids(account.id) | {account.id}
    return (
        Account.query
        .filter(
            Account.is_group.is_(True),
            Account.active.is_(True),
            Account.id.notin_(excluded_ids),
        )
        .order_by(Account.code)
        .all()
    )


@bp.get("/accounts")
@permission_required("accounting.view")
def accounts():
    all_accounts=Account.query.order_by(Account.code).all()
    tree=_children_tree(all_accounts)
    stats={
        "count":len(all_accounts),
        "groups":sum(1 for a in all_accounts if a.is_group),
        "leaves":sum(1 for a in all_accounts if not a.is_group),
        "balance":sum((account_balance(a.id) for a in all_accounts if not a.is_group),0),
    }
    return render_template("accounting/accounts.html",tree=tree,flat_accounts=all_accounts,stats=stats,
                           account_type_labels=ACCOUNT_TYPE_LABELS,balance_func=account_balance,can_manage=can("accounting.manage"))

@bp.route("/accounts/new",methods=["GET","POST"])
@permission_required("accounting.manage")
def account_new():
    parents=Account.query.filter_by(is_group=True,active=True).order_by(Account.code).all()
    parent_id=request.form.get("parent_id",type=int) if request.method=="POST" else request.args.get("parent_id",type=int)
    selected_parent=db.session.get(Account,parent_id) if parent_id else (parents[0] if parents else None)
    if request.method=="POST":
        try:
            parent=db.session.get(Account,int(request.form["parent_id"]))
            if not parent or not parent.is_group: raise ValueError("اختر حسابًا أبًا تجميعيًا")
            name=request.form.get("name","").strip()
            if not name: raise ValueError("اسم الحساب مطلوب")
            is_group=request.form.get("is_group")=="1"
            opening_balance=Decimal(str(request.form.get("opening_balance","0") or "0")).quantize(Decimal("0.01"))
            if opening_balance < 0: raise ValueError("الرصيد الافتتاحي لا يمكن أن يكون سالبًا")
            if is_group and opening_balance != 0: raise ValueError("الحساب التجميعي لا يحمل رصيدًا افتتاحيًا؛ استخدم حسابًا تفصيليًا")
            opening_side=request.form.get("opening_side","auto")
            code=_next_code(parent)
            while Account.query.filter_by(code=code).first():
                code=f"{parent.code}{int(code[len(parent.code):])+1:02d}"
            account=Account(code=code,name=name,account_type=parent.account_type,parent_id=parent.id,is_group=is_group,
                            active=True,allow_manual_posting=not is_group)
            db.session.add(account); db.session.flush()

            opening_entry_number=None
            if opening_balance > 0:
                opening_account=get_system_account("opening_balance_equity")
                debit_by_nature=account.account_type in {"asset","expense"}
                is_debit=(debit_by_nature if opening_side=="auto" else opening_side=="debit")
                lines=[
                    {"account":account,"debit":opening_balance if is_debit else Decimal("0"),"credit":opening_balance if not is_debit else Decimal("0"),
                     "description":"الرصيد الافتتاحي"},
                    {"account":opening_account,"debit":opening_balance if not is_debit else Decimal("0"),"credit":opening_balance if is_debit else Decimal("0"),
                     "description":f"مقابل رصيد افتتاحي للحساب {account.code}"},
                ]
                opening_entry=create_posted_entry(
                    description=f"رصيد افتتاحي — {account.name}",
                    entry_date=date.today(),
                    created_by_id=current_user.id,
                    lines=lines,
                    source_type="opening_balance",
                    source_id=account.id,
                    prefix="OPEN",
                    audit=f"الرصيد الافتتاحي للحساب {account.code}: {opening_balance}",
                )
                opening_entry_number=opening_entry.number
            audit("create","account",account.id,f"{account.code}|{account.name}|opening={opening_balance}")
            db.session.commit()
            message=f"تم إنشاء الحساب {account.name} برمز {account.code}"
            if opening_entry_number: message += f" وترحيل الرصيد الافتتاحي في {opening_entry_number}"
            flash(message,"success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    auto_codes={p.id:_next_code(p) for p in parents}
    default_opening_side="debit" if (selected_parent and selected_parent.account_type in {"asset","expense"}) else "credit"
    return render_template("accounting/account_form.html",parents=parents,selected_parent=selected_parent,auto_codes=auto_codes,default_opening_side=default_opening_side)

@bp.route("/accounts/<int:account_id>/edit",methods=["GET","POST"])
@permission_required("accounting.manage")
def account_edit(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key:
        flash("الحساب النظامي محمي ولا يمكن تغيير بنيته","warning")
    if request.method=="POST":
        try:
            if account.system_key: raise ValueError("لا يمكن تعديل الحسابات النظامية")
            name=request.form.get("name","").strip()
            parent=db.session.get(Account,request.form.get("parent_id",type=int))
            if not name:
                raise ValueError("اسم الحساب مطلوب")
            if not parent or not parent.is_group or not parent.active:
                raise ValueError("اختر حسابًا أبًا تجميعيًا ونشطًا")
            if _would_create_account_cycle(account.id, parent.id):
                raise ValueError("لا يمكن نقل الحساب إلى نفسه أو إلى أحد فروعه؛ سيؤدي ذلك إلى دورة في شجرة الحسابات")
            account.name=name
            account.parent_id=parent.id
            account.active=request.form.get("active")=="1"
            account.allow_manual_posting=not account.is_group and request.form.get("allow_manual_posting")=="1"
            audit("update","account",account.id,account.code); db.session.commit(); flash("تم تحديث الحساب","success")
            return redirect(url_for("accounting.accounts"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    parents=_eligible_account_parents(account)
    return render_template("accounting/account_edit.html",account=account,parents=parents)

@bp.post("/accounts/<int:account_id>/delete")
@permission_required("accounting.manage")
def account_delete(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key:
        flash("الحساب النظامي محمي ولا يمكن حذفه","warning")
        return redirect(url_for("accounting.accounts"))
    if account.children:
        flash("لا يمكن حذف حساب يحتوي على فروع. احذف الفروع أو عطّل الحساب بدلًا من ذلك","warning")
        return redirect(url_for("accounting.accounts"))
    reference=_account_references(account.id)
    if reference:
        flash(f"لا يمكن حذف الحساب لأنه مستخدم في {reference}. يمكن إيقافه بدلًا من الحذف.","warning")
        return redirect(url_for("accounting.accounts"))
    try:
        audit("delete","account",account.id,f"{account.code}|{account.name}")
        db.session.delete(account)
        db.session.commit()
        flash("تم حذف الحساب نهائيًا لأنه لم يُستخدم في أي حركة","success")
    except Exception as exc:
        db.session.rollback()
        flash(f"تعذر حذف الحساب بأمان: {exc}","danger")
    return redirect(url_for("accounting.accounts"))

@bp.post("/accounts/<int:account_id>/toggle")
@permission_required("accounting.manage")
def account_toggle(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("غير موجود",404)
    if account.system_key: flash("الحساب النظامي محمي","warning")
    elif account.children: flash("لا يمكن إيقاف حساب له فروع","warning")
    else:
        account.active=not account.active; audit("toggle","account",account.id,str(account.active)); db.session.commit()
    return redirect(url_for("accounting.accounts"))

@bp.get("/journal")
@permission_required("accounting.view")
def journal():
    source=request.args.get("source","").strip()
    query=request.args.get("q","").strip()
    sort=request.args.get("sort","latest")

    q=JournalEntry.query
    if source:
        q=q.filter(JournalEntry.source_type==source)
    if query:
        like=f"%{query}%"
        q=q.filter((JournalEntry.number.ilike(like)) | (JournalEntry.description.ilike(like)))

    if sort=="oldest":
        q=q.order_by(JournalEntry.entry_date.asc(),JournalEntry.id.asc())
    elif sort=="highest":
        rows=q.all()
        rows.sort(key=lambda e:e.totals()[0],reverse=True)
        entries=rows[:500]
    elif sort=="lowest":
        rows=q.all()
        rows.sort(key=lambda e:e.totals()[0])
        entries=rows[:500]
    else:
        q=q.order_by(JournalEntry.entry_date.desc(),JournalEntry.id.desc())
        entries=q.limit(500).all()

    if sort not in {"highest","lowest"}:
        entries=entries[:500]

    source_labels={
        "voucher":"سند",
        "expense":"مصروف",
        "settlement":"تسوية",
        "payroll":"رواتب",
        "rent":"إيجار",
        "rent_payment":"تحصيل إيجار",
        "salary_payment":"صرف راتب",
        "gate":"البوابة",
        "manual":"قيد يدوي",
        "employee_daily":"يومية موظف",
        "client_daily":"يومية عميل",
        "reverse":"قيد عكسي",
        "opening_balance":"رصيد افتتاحي",
    }
    return render_template("accounting/journal.html",
        entries=entries,source=source,query=query,sort=sort,source_labels=source_labels)

@bp.get("/journal/<int:entry_id>")
@permission_required("accounting.view")
def journal_detail(entry_id):
    return render_template("accounting/journal_detail.html",entry=db.session.get(JournalEntry,entry_id),can_reverse=can("accounting.post"))

@bp.post("/journal/<int:entry_id>/reverse")
@permission_required("accounting.post")
def reverse(entry_id):
    try:
        e=db.session.get(JournalEntry,entry_id)
        r=reverse_entry(e,current_user.id,request.form.get("reason","تصحيح"))
        audit("reverse_journal","journal_entry",e.id,r.number); db.session.commit(); flash(f"تم عكس القيد إلى {r.number}","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("accounting.journal_detail",entry_id=entry_id))


@bp.get("/fiscal-years")
@permission_required("accounting.view")
def fiscal_years():
    rows = FiscalYear.query.order_by(FiscalYear.start_date.desc(), FiscalYear.id.desc()).all()
    return render_template("accounting/fiscal_years.html", rows=rows)


@bp.post("/fiscal-years")
@permission_required("accounting.view")
def fiscal_year_create():
    if not can("accounting.periods.manage"):
        from flask import abort
        abort(403)
    try:
        name = request.form.get("name", "").strip()[:80]
        start_date = date.fromisoformat(request.form.get("start_date", ""))
        end_date = date.fromisoformat(request.form.get("end_date", ""))
        notes = request.form.get("notes", "").strip() or None
        if not name:
            raise ValueError("اسم السنة المالية مطلوب")
        if end_date < start_date:
            raise ValueError("تاريخ نهاية السنة يجب ألا يسبق تاريخ بدايتها")
        if FiscalYear.query.filter_by(name=name).first():
            raise ValueError("اسم السنة المالية مستخدم مسبقًا")
        overlap = FiscalYear.query.filter(
            FiscalYear.start_date <= end_date,
            FiscalYear.end_date >= start_date,
        ).first()
        if overlap:
            raise ValueError(f"الفترة تتداخل مع السنة المالية «{overlap.name}»")
        latest = FiscalYear.query.order_by(FiscalYear.end_date.desc()).first()
        if latest and start_date <= latest.end_date:
            raise ValueError("يجب إنشاء السنوات المالية بالتسلسل الزمني بعد آخر سنة موجودة")
        row = FiscalYear(name=name, start_date=start_date, end_date=end_date,
                         notes=notes, status="open", created_by_id=current_user.id)
        db.session.add(row)
        db.session.flush()
        audit("create_fiscal_year", "fiscal_year", row.id, f"{name}|{start_date}|{end_date}")
        db.session.commit()
        flash("تم إنشاء السنة المالية بنجاح", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("accounting.fiscal_years"))


@bp.post("/fiscal-years/<int:fiscal_year_id>/close")
@permission_required("accounting.periods.manage")
def fiscal_year_close(fiscal_year_id):
    year = db.session.get(FiscalYear, fiscal_year_id)
    if not year:
        return ("السنة المالية غير موجودة", 404)
    try:
        if year.status == "closed":
            raise ValueError("هذه السنة المالية مقفلة مسبقًا")
        earlier_open = FiscalYear.query.filter(
            FiscalYear.status == "open", FiscalYear.end_date < year.start_date,
        ).first()
        if earlier_open:
            raise ValueError(f"يجب إقفال السنة المالية السابقة «{earlier_open.name}» أولًا")
        drafts = JournalEntry.query.filter(
            JournalEntry.status == "draft",
            JournalEntry.entry_date >= year.start_date,
            JournalEntry.entry_date <= year.end_date,
        ).count()
        if drafts:
            raise ValueError("لا يمكن إقفال السنة قبل ترحيل أو إلغاء جميع القيود المسودة داخلها")

        pnl_accounts = Account.query.filter(
            Account.is_group.is_(False),
            Account.account_type.in_(["revenue", "expense"]),
        ).order_by(Account.code).all()
        close_lines = []
        signed_total = Decimal("0")
        for account in pnl_accounts:
            balance = account_balance(account.id, start=year.start_date, end=year.end_date)
            if not balance:
                continue
            signed_total += balance
            if balance > 0:
                close_lines.append({"account": account, "debit": Decimal("0"), "credit": balance,
                                    "description": f"إقفال حساب {account.code} — {account.name}"})
            else:
                close_lines.append({"account": account, "debit": abs(balance), "credit": Decimal("0"),
                                    "description": f"إقفال حساب {account.code} — {account.name}"})

        net_income = -signed_total
        closing_entry = None
        if close_lines:
            retained = get_system_account("retained_earnings")
            if net_income > 0:
                close_lines.append({"account": retained, "debit": Decimal("0"), "credit": net_income,
                                    "description": f"صافي ربح السنة المالية {year.name}"})
            elif net_income < 0:
                close_lines.append({"account": retained, "debit": abs(net_income), "credit": Decimal("0"),
                                    "description": f"صافي خسارة السنة المالية {year.name}"})
            closing_entry = create_posted_entry(
                description=f"إقفال نتائج السنة المالية {year.name}",
                entry_date=year.end_date, created_by_id=current_user.id, lines=close_lines,
                source_type="fiscal_year_close", source_id=year.id, prefix="CLOSE",
                audit=f"إقفال السنة {year.name} | صافي النتيجة={net_income}",
            )
        year.status = "closed"
        year.closed_at = datetime.now(timezone.utc)
        year.closed_by_id = current_user.id
        year.closing_journal_entry_id = closing_entry.id if closing_entry else None
        audit("close_fiscal_year", "fiscal_year", year.id,
              f"{year.name}|net_income={net_income}|closing_entry={closing_entry.number if closing_entry else 'none'}")
        db.session.commit()
        flash(f"تم إقفال السنة المالية {year.name} بنجاح" +
              (f" بالقيد {closing_entry.number}" if closing_entry else "؛ لا توجد حركة إيرادات أو مصروفات تحتاج إلى قيد إقفال"),
              "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("accounting.fiscal_years"))


def _daily_party_config(kind):
    if kind == "employee":
        return Employee, "employee_daily", "الموظف", "الموظفين", "full_name", ensure_employee_account, "EMP"
    if kind == "client":
        return Client, "client_daily", "العميل", "العملاء", "name", ensure_client_account, "CLI"
    raise ValueError("نوع اليومية غير صالح")


def _daily_account_options():
    rows = Account.query.filter_by(active=True).order_by(Account.code).all()
    children = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)
    flattened = []
    def walk(parent_id=None, depth=0):
        for row in sorted(children.get(parent_id, []), key=lambda x: x.code or ""):
            flattened.append((row, depth))
            walk(row.id, depth + 1)
    walk(None)
    cash_ids = set()
    for row in rows:
        if row.is_group or not row.allow_manual_posting:
            continue
        try:
            if is_cash_account(row):
                cash_ids.add(row.id)
        except Exception:
            if row.system_key == "main_cash":
                cash_ids.add(row.id)
    return flattened, cash_ids


def _daily_amount(raw):
    value = str(raw or "").strip()
    for src, dst in zip("٠١٢٣٤٥٦٧٨٩", "0123456789"):
        value = value.replace(src, dst)
    for src, dst in zip("۰۱۲۳۴۵۶۷۸۹", "0123456789"):
        value = value.replace(src, dst)
    value = value.replace("٫", ".").replace("٬", "").replace(",", "").replace(" ", "")
    if not value or value.count(".") > 1 or any(ch not in "0123456789." for ch in value):
        raise ValueError("أدخل مبلغًا صحيحًا بالأرقام فقط")
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
    except Exception:
        raise ValueError("أدخل مبلغًا صحيحًا")
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر")
    return amount


def _daily_journals_page(kind):
    model, source_type, singular, plural, name_attr, ensure_account, prefix = _daily_party_config(kind)
    endpoint = "accounting.employee_journals" if kind == "employee" else "accounting.client_journals"
    parties = model.query.order_by(getattr(model, name_attr)).all()
    show_form = request.args.get("new") == "1"
    edit_id = request.args.get("edit", type=int)
    if request.method == "POST":
        show_form = True
        edit_id = request.form.get("edit_entry_id", type=int) or None
        try:
            if not can("accounting.post"):
                raise ValueError("ليست لديك صلاحية إضافة أو تعديل اليوميات")
            party = db.session.get(model, request.form.get("party_id", type=int))
            if not party or not party.active:
                raise ValueError(f"اختر {singular} نشطًا")
            party_account = ensure_account(party)
            if not party_account or party_account.is_group or not party_account.active or not party_account.allow_manual_posting:
                raise ValueError(f"لا يوجد حساب تفصيلي نشط لـ{singular}")
            cash = db.session.get(Account, request.form.get("cash_account_id", type=int))
            try:
                valid_cash = bool(cash and is_cash_account(cash))
            except Exception:
                valid_cash = bool(cash and cash.system_key == "main_cash")
            if not cash or not cash.active or cash.is_group or not cash.allow_manual_posting or not valid_cash:
                raise ValueError("اختر صندوقًا تفصيليًا نشطًا من شجرة الحسابات")
            if cash.id == party_account.id:
                raise ValueError("حساب الطرف والصندوق يجب أن يكونا مختلفين")
            side = (request.form.get("party_side") or "").strip()
            if side not in {"debit", "credit"}:
                raise ValueError("اختر طبيعة اليومية: مدين أو دائن")
            amount = _daily_amount(request.form.get("amount"))
            description = (request.form.get("description") or "").strip()
            if not description:
                raise ValueError("البيان إجباري")
            if len(description) > 500:
                raise ValueError("البيان أطول من الحد المسموح")
            try:
                entry_date = date.fromisoformat(request.form.get("entry_date") or date.today().isoformat())
            except ValueError:
                raise ValueError("تاريخ اليومية غير صحيح")

            original = None
            if edit_id:
                original = JournalEntry.query.filter_by(id=edit_id, source_type=source_type).with_for_update().first()
                if not original:
                    raise ValueError("اليومية المطلوب تعديلها غير موجودة")
                if original.status != "posted" or original.reversed_entry_id:
                    raise ValueError("لا يمكن تعديل يومية غير مرحلة أو سبق عكسها")
                # Preserve accounting history: reverse the prior posted entry, then post its replacement.
                reverse_entry(original, current_user.id, f"عكس قبل تعديل يومية {singular}")

            lines = [
                {"account": party_account, "debit": amount if side == "debit" else 0,
                 "credit": amount if side == "credit" else 0, "description": description},
                {"account": cash, "debit": amount if side == "credit" else 0,
                 "credit": amount if side == "debit" else 0, "description": description},
            ]
            entry = create_posted_entry(
                description=description, entry_date=entry_date, created_by_id=current_user.id,
                lines=lines, source_type=source_type, source_id=party.id, prefix=prefix,
                audit=f"{'تعديل' if original else 'إضافة'} يومية {singular}: {getattr(party, name_attr)}",
            )
            audit("edit" if original else "create", f"{kind}_daily_journal", entry.id,
                  f"{getattr(party, name_attr)}|{entry.number}|{amount}|{side}")
            db.session.commit()
            flash((f"تم تعديل اليومية وترحيل القيد الجديد {entry.number} مع حفظ أثر القيد السابق"
                   if original else f"تمت إضافة اليومية وترحيل القيد {entry.number}"), "success")
            return redirect(url_for(endpoint))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    edit_entry = None
    if edit_id:
        edit_entry = JournalEntry.query.filter_by(id=edit_id, source_type=source_type).first()
        if edit_entry and (edit_entry.status != "posted" or edit_entry.reversed_entry_id):
            edit_entry = None
        if edit_entry:
            show_form = True
        elif request.method != "POST" and request.args.get("edit"):
            flash("لا يمكن تعديل هذه اليومية؛ ربما عُكست أو لم تعد موجودة", "warning")

    account_options, cash_account_ids = _daily_account_options()
    party_map = {p.id: p for p in parties}
    selected_filter = request.args.get("party_id", type=int)
    start_raw, end_raw = request.args.get("start", "").strip(), request.args.get("end", "").strip()
    search, sort = request.args.get("q", "").strip(), request.args.get("sort", "latest")
    if sort not in {"latest", "oldest", "highest", "lowest"}:
        sort = "latest"
    query = JournalEntry.query.filter_by(source_type=source_type)
    if selected_filter:
        query = query.filter(JournalEntry.source_id == selected_filter)
    for raw, label in ((start_raw, "البداية"), (end_raw, "النهاية")):
        if raw:
            try:
                parsed = date.fromisoformat(raw)
                query = query.filter(JournalEntry.entry_date >= parsed if label == "البداية" else JournalEntry.entry_date <= parsed)
            except ValueError:
                flash(f"تاريخ {label} غير صالح وتم تجاهله", "warning")
    if search:
        like = f"%{search}%"
        query = query.filter((JournalEntry.number.ilike(like)) | (JournalEntry.description.ilike(like)))
    if sort == "oldest":
        entries = query.order_by(JournalEntry.entry_date.asc(), JournalEntry.id.asc()).limit(500).all()
    elif sort in {"highest", "lowest"}:
        entries = query.order_by(JournalEntry.id.desc()).limit(1000).all()
        entries.sort(key=lambda row: (row.totals()[0], row.id), reverse=(sort == "highest"))
        entries = entries[:500]
    else:
        entries = query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()).limit(500).all()

    edit_party_id = edit_entry.source_id if edit_entry else None
    edit_party = party_map.get(edit_party_id) if edit_party_id else None
    edit_party_account = getattr(edit_party, "account_id", None) if edit_party else None
    edit_cash_id, edit_side, edit_amount = None, "", ""
    if edit_entry:
        edit_amount = f"{edit_entry.totals()[0]:.2f}"
        for line in edit_entry.lines:
            if edit_party_account and line.account_id == edit_party_account:
                edit_side = "debit" if line.debit > 0 else "credit"
            else:
                edit_cash_id = line.account_id
    submitted_party = request.form.get("party_id", str(edit_party_id) if edit_party_id else "")
    return render_template(
        "accounting/party_journals.html", kind=kind, singular=singular, plural=plural, name_attr=name_attr,
        entries=entries, parties=parties, party_map=party_map, selected_filter=selected_filter,
        start_raw=start_raw, end_raw=end_raw, search=search, sort=sort, account_options=account_options,
        cash_account_ids=cash_account_ids, show_form=show_form, edit_entry=edit_entry,
        edit_party_id=edit_party_id, edit_cash_id=edit_cash_id, edit_side=edit_side, edit_amount=edit_amount,
        submitted_party=submitted_party, today=date.today(),
        form_values=request.form if request.method == "POST" else {},
    )


@bp.route("/employee-journals", methods=["GET", "POST"])
@permission_required("accounting.view")
def employee_journals():
    return _daily_journals_page("employee")


@bp.route("/client-journals", methods=["GET", "POST"])
@permission_required("accounting.view")
def client_journals():
    return _daily_journals_page("client")


@bp.post("/<string:kind>-journals/<int:entry_id>/reverse")
@permission_required("accounting.post")
def party_journal_reverse(kind, entry_id):
    if kind not in {"employee", "client"}:
        return ("نوع اليومية غير صالح", 404)
    _, source_type, singular, _, _, _, _ = _daily_party_config(kind)
    entry = JournalEntry.query.filter_by(id=entry_id, source_type=source_type).first()
    try:
        if not entry:
            raise ValueError("اليومية غير موجودة")
        reverse = reverse_entry(entry, current_user.id, request.form.get("reason", f"عكس يومية {singular}"))
        audit("reverse_party_journal", f"{kind}_daily_journal", entry.id, reverse.number)
        db.session.commit()
        flash(f"تم إنشاء القيد العكسي {reverse.number} مع الحفاظ على اليومية الأصلية", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    endpoint = "accounting.employee_journals" if kind == "employee" else "accounting.client_journals"
    return redirect(url_for(endpoint))
