from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import func
from ..extensions import db
from ..models import Account, JournalEntry, JournalLine, EntryStatus

def D(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))

def next_number(prefix="JE"):
    day=datetime.now(timezone.utc).strftime("%Y%m%d")
    count=db.session.query(func.count(JournalEntry.id)).scalar() or 0
    return f"{prefix}-{day}-{count+1:05d}"

def get_system_account(key):
    account=db.session.query(Account).filter_by(system_key=key).one_or_none()
    if not account:
        raise ValueError(f"الحساب النظامي غير مهيأ: {key}")
    return account

def account_balance(account_id, start=None, end=None):
    q=db.session.query(func.coalesce(func.sum(JournalLine.debit-JournalLine.credit),0)).join(JournalEntry)
    q=q.filter(JournalLine.account_id==account_id, JournalEntry.status==EntryStatus.POSTED.value)
    if start: q=q.filter(JournalEntry.entry_date>=start)
    if end: q=q.filter(JournalEntry.entry_date<=end)
    return D(q.scalar())

def create_posted_entry(*, description, entry_date, created_by_id, lines,
                        source_type="manual", source_id=None, prefix="JE", audit=None):
    normalized=[]; debit_total=Decimal("0"); credit_total=Decimal("0")
    for item in lines:
        account=item.get("account")
        if not account or account.is_group or not account.allow_manual_posting:
            raise ValueError("لا يمكن الترحيل على حساب رئيسي أو حساب غير قابل للقيد")
        debit=D(item.get("debit")); credit=D(item.get("credit"))
        if (debit>0)==(credit>0):
            raise ValueError("كل سطر يجب أن يحتوي مدينًا أو دائنًا واحدًا فقط")
        debit_total+=debit; credit_total+=credit
        normalized.append((account,debit,credit,item.get("description"),item.get("reference")))
    if not normalized or debit_total<=0 or debit_total!=credit_total:
        raise ValueError("القيد غير متزن أو فارغ")
    entry=JournalEntry(number=next_number(prefix),entry_date=entry_date,description=description,
        status=EntryStatus.POSTED.value,source_type=source_type,source_id=source_id,
        created_by_id=created_by_id,posted_at=datetime.now(timezone.utc))
    db.session.add(entry); db.session.flush()
    for account,debit,credit,line_desc,reference in normalized:
        db.session.add(JournalLine(entry_id=entry.id,account_id=account.id,
            debit=debit,credit=credit,description=line_desc or description,reference=reference))
    if audit:
        from .audit import audit as add_audit
        add_audit("post_journal", "journal_entry", entry.id, audit)
    return entry

def reverse_entry(entry, user_id, reason):
    if entry.status != EntryStatus.POSTED.value:
        raise ValueError("يمكن عكس القيد المرحل فقط")
    lines=[]
    for line in entry.lines:
        lines.append({"account":line.account,"debit":line.credit,"credit":line.debit,
                      "description":f"عكس: {line.description or entry.description}","reference":entry.number})
    reverse=create_posted_entry(description=f"عكس القيد {entry.number}: {reason}",entry_date=date.today(),
        created_by_id=user_id,lines=lines,source_type="reverse",source_id=entry.id,prefix="REV")
    entry.reversed_entry_id=reverse.id
    entry.status="void"
    return reverse
