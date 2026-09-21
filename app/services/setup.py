from ..extensions import db
from ..models import Account, AccountType, Permission, User, Role, VehicleType
from ..permissions import seed_permissions

ROOTS=[
("1","الأصول",AccountType.ASSET.value,"root_assets"),
("2","الخصوم",AccountType.LIABILITY.value,"root_liabilities"),
("3","حقوق الملكية",AccountType.EQUITY.value,"root_equity"),
("4","الإيرادات",AccountType.REVENUE.value,"root_revenue"),
("5","المصروفات",AccountType.EXPENSE.value,"root_expenses")]

CHILDREN=[
("101","الصناديق",AccountType.ASSET.value,"root_assets",True,"cash_root"),
("10101","الصندوق الرئيسي",AccountType.ASSET.value,"cash_root",False,"main_cash"),
("102","عهد الموظفين والمتحصلين",AccountType.ASSET.value,"root_assets",True,"collector_root"),
("103","حسابات العملاء",AccountType.ASSET.value,"root_assets",True,"clients_root"),
("104","حسابات الوكلاء",AccountType.ASSET.value,"root_assets",True,"agents_root"),
("201","مستحقات الرواتب",AccountType.LIABILITY.value,"root_liabilities",True,"payable_root"),
("20101","مخصص مستحقات الرواتب",AccountType.LIABILITY.value,"payable_root",False,"salary_payable"),
("20201","التزامات استقطاعات الرواتب",AccountType.LIABILITY.value,"root_liabilities",False,"salary_deduction_liability"),
("401","إيرادات دخول السوق",AccountType.REVENUE.value,"root_revenue",False,"entry_revenue"),
("402","إيرادات الإيجارات",AccountType.REVENUE.value,"root_revenue",False,"rent_revenue"),
("403","إيرادات أخرى",AccountType.REVENUE.value,"root_revenue",False,"other_revenue"),
("501","الرواتب والأجور",AccountType.EXPENSE.value,"root_expenses",False,"salary_expense"),
("502","مصروفات تشغيلية",AccountType.EXPENSE.value,"root_expenses",False,"operating_expense")]

def account_by_key(key):
    return db.session.query(Account).filter_by(system_key=key).one()

def ensure_system_accounts():
    for code,name,typ,key in ROOTS:
        if not db.session.query(Account).filter_by(system_key=key).first():
            db.session.add(Account(code=code,name=name,account_type=typ,is_group=True,
                allow_manual_posting=False,system_key=key))
    db.session.flush()
    for code,name,typ,parent_key,is_group,key in CHILDREN:
        if not db.session.query(Account).filter_by(system_key=key).first():
            parent=account_by_key(parent_key)
            db.session.add(Account(code=code,name=name,account_type=typ,parent_id=parent.id,
                is_group=is_group,allow_manual_posting=not is_group,system_key=key))
    db.session.flush()

def ensure_admin(username="admin",password="admin"):
    user=db.session.query(User).filter_by(username=username).first()
    if not user:
        user=User(username=username,full_name="مدير النظام",role=Role.ADMIN.value,active=True)
        user.set_password(password)
        db.session.add(user)
    return user

def seed():
    ensure_system_accounts()
    seed_permissions()
    ensure_admin()
    defaults=["دينه","قلاب","ناقلة","شاص","باص","سوزوكي","أخرى"]
    for name in defaults:
        if not db.session.query(VehicleType).filter_by(name=name).first():
            db.session.add(VehicleType(name=name,is_system=True))
    db.session.commit()
