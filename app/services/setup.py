from ..extensions import db
from ..models import Account, AccountType, Employee, Role, Setting, User, VehicleType
from ..permissions import seed_permissions
from .accounts import ensure_employee_account, ensure_employee_payroll_account

ROOTS=[
("1","الأصول",AccountType.ASSET.value,"root_assets"),
("2","الخصوم",AccountType.LIABILITY.value,"root_liabilities"),
("3","حقوق الملكية",AccountType.EQUITY.value,"root_equity"),
("4","الإيرادات",AccountType.REVENUE.value,"root_revenue"),
("5","المصروفات",AccountType.EXPENSE.value,"root_expenses")]

CHILDREN=[
("101","الصناديق",AccountType.ASSET.value,"root_assets",True,"cash_root"),
("10101","الصندوق الرئيسي",AccountType.ASSET.value,"cash_root",False,"main_cash"),
("102","صناديق الموظفين",AccountType.ASSET.value,"cash_root",True,"collector_root"),
("103","حسابات العملاء",AccountType.ASSET.value,"root_assets",True,"clients_root"),
("105","حسابات الموظفين",AccountType.ASSET.value,"root_assets",True,"employee_accounts_root"),
("104","حسابات الوكلاء",AccountType.ASSET.value,"root_assets",True,"agents_root"),
("201","مستحقات الرواتب",AccountType.LIABILITY.value,"root_liabilities",True,"payable_root"),
("20101","مخصص مستحقات الرواتب",AccountType.LIABILITY.value,"payable_root",False,"salary_payable"),
("20201","التزامات استقطاعات الرواتب",AccountType.LIABILITY.value,"root_liabilities",False,"salary_deduction_liability"),
("401","إيرادات دخول السوق",AccountType.REVENUE.value,"root_revenue",False,"entry_revenue"),
("402","إيرادات الإيجارات",AccountType.REVENUE.value,"root_revenue",False,"rent_revenue"),
("403","إيرادات أخرى",AccountType.REVENUE.value,"root_revenue",False,"other_revenue"),
("404","إيرادات خروج السوق",AccountType.REVENUE.value,"root_revenue",False,"exit_revenue"),
("405","إيرادات غرامات ومخالفات الموظفين",AccountType.REVENUE.value,"root_revenue",False,"employee_fines_revenue"),
("39901","أرصدة افتتاحية",AccountType.EQUITY.value,"root_equity",False,"opening_balance_equity"),
("501","الرواتب والأجور",AccountType.EXPENSE.value,"root_expenses",False,"salary_expense"),
("502","مصروفات تشغيلية",AccountType.EXPENSE.value,"root_expenses",False,"operating_expense")]

def account_by_key(key):
    return db.session.query(Account).filter_by(system_key=key).one()

def ensure_system_accounts():
    for code,name,typ,key in ROOTS:
        if not db.session.query(Account).filter_by(system_key=key).first():
            db.session.add(Account(code=code,name=name,account_type=typ,is_group=True,allow_manual_posting=False,system_key=key))
    db.session.flush()
    for code,name,typ,parent_key,is_group,key in CHILDREN:
        if not db.session.query(Account).filter_by(system_key=key).first():
            parent=account_by_key(parent_key)
            db.session.add(Account(code=code,name=name,account_type=typ,parent_id=parent.id,is_group=is_group,allow_manual_posting=not is_group,system_key=key))
    db.session.flush()

def ensure_admin(username="admin",password="admin"):
    user=db.session.query(User).filter_by(username=username).first()
    if not user:
        user=User(username=username,full_name="مدير النظام",role=Role.ADMIN.value,active=True)
        user.set_password(password)
        db.session.add(user)
    else:
        user.role=Role.ADMIN.value
        user.active=True
    return user

def ensure_employees_for_users():
    users=User.query.order_by(User.id).all()
    for user in users:
        if user.employee:
            continue
        last=Employee.query.order_by(Employee.id.desc()).first()
        next_id=(last.id+1) if last else 1
        emp=Employee(
            code=f"EMP-{next_id:05d}",
            full_name=user.full_name or user.username,
            phone=user.phone,
            job_title="مدير النظام" if user.role==Role.ADMIN.value else ("متحصل" if user.role==Role.COLLECTOR.value else "موظف"),
            monthly_salary=0,
            active=user.active,
            employment_type="دوام كامل",
            weekly_hours=48,
            work_days="0,1,2,3,4,5",
        )
        db.session.add(emp)
        db.session.flush()
        user.employee_id=emp.id
        ensure_employee_account(emp)
        from .accounts import ensure_employee_cashbox
        ensure_employee_cashbox(emp)
        ensure_employee_payroll_account(emp)

def seed():
    ensure_system_accounts()
    seed_permissions()
    ensure_admin()
    ensure_employees_for_users()
    defaults=[
        ("organization_name","سوق الجملة","string","اسم المنشأة"),
        ("project_name","سوق الجملة","string","اسم المشروع الظاهر"),
        ("currency_name","ريال يمني","string","العملة"),
        ("ui_theme","light","string","المظهر"),
        ("customer_portal","0","boolean","إتاحة لوحة العميل"),
        ("brand_color","#0b6e4f","string","اللون الرئيسي"),
        ("brand_version","1","string","نسخة الهوية"),
    ]
    for key,value,value_type,description in defaults:
        row=Setting.query.filter_by(key=key).first()
        if not row:
            db.session.add(Setting(key=key,value=value,value_type=value_type,description=description))
    for name in ["خصوصي","نقل","دينة","قلاب","ناقلة","شاص","باص","سوزوكي","صهريج","معدات","أخرى","افتراضي"]:
        existing_type=db.session.query(VehicleType).filter_by(name=name).first()
        if not existing_type:
            db.session.add(VehicleType(name=name,is_system=True))
        elif name=="افتراضي":
            existing_type.active=True
            existing_type.is_system=True
    db.session.commit()
