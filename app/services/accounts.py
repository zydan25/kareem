from ..extensions import db
from ..models import Account

def ensure_system():
    from .setup import ensure_system_accounts
    ensure_system_accounts()

def ensure_child_account(*, parent_key, code, name, system_key=None, account_type="asset"):
    ensure_system()
    if system_key:
        existing=db.session.query(Account).filter_by(system_key=system_key).first()
        if existing:
            return existing
    existing=db.session.query(Account).filter_by(code=code).first()
    if existing:
        return existing
    from .setup import account_by_key
    parent=account_by_key(parent_key)
    account=Account(code=code,name=name,account_type=account_type,parent_id=parent.id,
        is_group=False,active=True,allow_manual_posting=True,system_key=system_key)
    db.session.add(account)
    db.session.flush()
    return account

def ensure_agent_account(agent):
    if agent.account_id:
        return agent.account
    db.session.flush()
    account=ensure_child_account(parent_key="agents_root",code=f"104{agent.id:06d}",
        name=f"وكيل: {agent.name}",account_type="asset")
    agent.account_id=account.id
    return account

def ensure_client_account(client):
    if client.account_id:
        return client.account
    db.session.flush()
    account=ensure_child_account(parent_key="clients_root",code=f"103{client.id:06d}",
        name=f"عميل: {client.name}",account_type="asset")
    client.account_id=account.id
    return account

def ensure_employee_account(employee):
    if employee.account_id:
        return employee.account
    db.session.flush()
    account=ensure_child_account(parent_key="employee_accounts_root",code=f"105E{employee.id:06d}",
        name=f"حساب موظف: {employee.full_name}",account_type="asset")
    employee.account_id=account.id
    return account

def ensure_employee_cashbox(employee):
    if employee.cashbox_account_id:
        return employee.cashbox_account
    db.session.flush()
    account=ensure_child_account(parent_key="collector_root",code=f"102E{employee.id:06d}",
        name=f"صندوق موظف: {employee.full_name}",account_type="asset")
    employee.cashbox_account_id=account.id
    return account

def ensure_employee_payroll_account(employee):
    if employee.payroll_account_id:
        return employee.payroll_account
    db.session.flush()
    account=ensure_child_account(parent_key="payable_root",code=f"203{employee.id:06d}",
        name=f"مستحق راتب: {employee.full_name}",account_type="liability")
    employee.payroll_account_id=account.id
    return account

def ensure_user_collector_account(user):
    if user.employee_id and user.employee:
        return ensure_employee_cashbox(user.employee)
    db.session.flush()
    return ensure_child_account(parent_key="collector_root",code=f"102U{user.id:06d}",
        name=f"صندوق متحصل: {user.full_name}",account_type="asset")
