from datetime import datetime
from decimal import Decimal
from sqlalchemy import func
from ..extensions import db
from ..models import Account, JournalEntry, JournalLine, EntryStatus

def D(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))

def next_number(prefix="JE"):
    day = datetime.utcnow().strftime("%Y%m%d")
    count = db.session.query(func.count(JournalEntry.id)).scalar() or 0
    return f"{prefix}-{day}-{count + 1:05d}"

def get_system_account(key, session=None):
    session = session or db.session
    account = session.query(Account).filter_by(system_key=key).one_or_none()
    if not account:
        raise ValueError(f"الحساب النظامي غير مهيأ: {key}")
    return account

def create_posted_entry(*, description, entry_date, created_by_id, lines, source_type="manual", source_id=None, prefix="JE"):
    normalized=[]; debit_total=Decimal("0"); credit_total=Decimal("0")
    for item in lines:
        account=item.get("account")
        if not account or account.is_group or not account.allow_manual_posting:
            raise ValueError("لا يمكن الترحيل على حساب رئيسي/غير قابل للقيد")
        debit=D(item.get("debit")); credit=D(item.get("credit"))
        if (debit>0)==(credit>0):
            raise ValueError("كل سطر يجب أن يحتوي على مدين أو دائن فقط")
        debit_total+=debit; credit_total+=credit
        normalized.append((account,debit,credit,item.get("description"),item.get("reference")))
    if not normalized or debit_total <= 0 or debit_total != credit_total:
        raise ValueError("القيد غير متزن أو فارغ")
    entry=JournalEntry(number=next_number(prefix),entry_date=entry_date,description=description,
        status=EntryStatus.POSTED.value,source_type=source_type,source_id=source_id,
        created_by_id=created_by_id,posted_at=datetime.utcnow())
    db.session.add(entry); db.session.flush()
    for account,debit,credit,line_desc,reference in normalized:
        db.session.add(JournalLine(entry_id=entry.id,account_id=account.id,debit=debit,credit=credit,
            description=line_desc or description,reference=reference))
    return entry


def reverse_entry(entry, user_id, reason):
    if not entry:
        raise ValueError("القيد غير موجود")
    if entry.status != EntryStatus.POSTED.value:
        raise ValueError("يمكن عكس القيد المرحل فقط")
    if entry.reversed_entry_id:
        raise ValueError("تم عكس هذا القيد مسبقًا")
    lines=[]
    for line in entry.lines:
        lines.append({
            "account": line.account,
            "debit": line.credit,
            "credit": line.debit,
            "description": f"عكس: {line.description or entry.description}",
            "reference": entry.number,
        })
    reverse=create_posted_entry(
        description=f"عكس القيد {entry.number}: {reason}",
        entry_date=date.today(),created_by_id=user_id,source_type="reverse",source_id=entry.id,
        lines=lines,prefix="REV",audit=f"عكس القيد {entry.number}",
    )
    entry.reversed_entry_id=reverse.id
    entry.status=EntryStatus.VOID.value
    return reverse
