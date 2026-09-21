from ..extensions import db
from ..models import Account

def ensure_child_account(*, parent_key, code, name, system_key=None, account_type="asset"):
    if system_key:
        existing=db.session.query(Account).filter_by(system_key=system_key).first()
        if existing: return existing
    from .setup import account_by_key, ensure_system_accounts
    ensure_system_accounts()
    parent=account_by_key(parent_key)
    existing=db.session.query(Account).filter_by(code=code).first()
    if existing: return existing
    account=Account(code=code,name=name,account_type=account_type,parent_id=parent.id,
        is_group=False,allow_manual_posting=True,system_key=system_key)
    db.session.add(account); db.session.flush()
    return account
