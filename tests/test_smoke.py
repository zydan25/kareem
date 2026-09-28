from decimal import Decimal
import pytest
from app.models import Account, Employee, User, VehicleType, JournalEntry, JournalLine
from app.extensions import db
from app.services.accounting import create_posted_entry

def login(client):
    return client.post("/login",data={"identifier":"admin","password":"admin"},follow_redirects=True)

def test_seed_and_dashboard(client):
    response=login(client)
    assert response.status_code==200
    assert "سوق الجملة" in response.get_data(as_text=True)
    assert "مدير النظام" in response.get_data(as_text=True)

def test_migration_seeded_system_accounts(app):
    with app.app_context():
        assert db.session.query(Account).filter(Account.code.in_(["1","2","3","4","5"])).count()==5
        assert db.session.query(Account).filter(Account.is_group.is_(True)).count()>=10
        assert db.session.query(VehicleType).count()>=7

def test_balanced_entry_and_reject_unbalanced(app):
    with app.app_context():
        user=db.session.query(__import__("app.models",fromlist=["User"]).User).filter_by(username="admin").one()
        debit=db.session.query(Account).filter_by(system_key="main_cash").one()
        credit=db.session.query(Account).filter_by(system_key="entry_revenue").one()
        entry=create_posted_entry(description="اختبار",entry_date=__import__("datetime").date.today(),created_by_id=user.id,
            lines=[{"account":debit,"debit":Decimal("100")},{"account":credit,"credit":Decimal("100")}],prefix="TST")
        assert entry.totals()==(Decimal("100"),Decimal("100"))
        db.session.commit()
        with pytest.raises(ValueError):
            create_posted_entry(description="غير متزن",entry_date=__import__("datetime").date.today(),created_by_id=user.id,
                lines=[{"account":debit,"debit":Decimal("100")},{"account":credit,"credit":Decimal("90")}],prefix="BAD")

def test_login_bad_password(client):
    response=client.post("/login",data={"identifier":"admin","password":"wrong"},follow_redirects=True)
    assert "بيانات الدخول غير صحيحة" in response.get_data(as_text=True)

def test_employee_phone_normalization_handles_hidden_unicode(client):
    response=client.post("/login",data={"identifier":"775632256","password":"wrong"},follow_redirects=True)
    # The identifier must at least reach password validation; hidden Unicode
    # formatting in stored employee numbers must not cause a false user miss.
    assert "رقم الهاتف/اسم المستخدم" in response.get_data(as_text=True)
def test_employee_created_account_can_login(app):
    admin_client=app.test_client()
    login(admin_client)
    response=admin_client.post("/employees",data={
        "full_name":"موظف اختبار",
        "phone":"٧٧٧ ١٢٣ ٤٥٦",
        "job_title":"متحصل",
        "monthly_salary":"0",
        "weekly_hours":"48",
        "hire_date":"2026-09-28",
        "login_password":"pass1234",
        "login_role":"collector",
    },follow_redirects=False)
    assert response.status_code==302

    with app.app_context():
        employee=Employee.query.filter_by(full_name="موظف اختبار").one()
        user=User.query.filter_by(employee_id=employee.id).one()
        assert user.username=="777123456"
        assert user.phone=="777123456"
        assert employee.user.id==user.id
        assert user.check_password("pass1234")

    employee_client=app.test_client()
    employee_response=employee_client.post("/login",data={
        "identifier":"777123456",
        "password":"pass1234",
    },follow_redirects=False)
    assert employee_response.status_code==302
    assert employee_response.headers["Location"].endswith("/collector/")


def test_employee_login_accepts_hidden_bidi_marks_in_phone_and_password(app):
    from app.models import Role
    client=app.test_client()
    raw_phone="\u200f\u202a775 660 418\u202c\u200f"
    with app.app_context():
        employee=Employee(
            code="EMP-UNICODE", full_name="موظف اختبار رموز", phone=raw_phone,
            job_title="متحصل", active=True
        )
        db.session.add(employee)
        db.session.flush()
        user=User(
            username=raw_phone, full_name=employee.full_name, phone=raw_phone,
            role=Role.COLLECTOR.value, active=True, employee_id=employee.id
        )
        user.set_password("775660418")
        db.session.add(user)
        db.session.commit()

    response=client.post("/login",data={
        "identifier":"775660418",
        "password":"\u200f775660418\u202c",
    },follow_redirects=False)
    assert response.status_code==302
    assert response.headers["Location"].endswith("/collector/")


def test_admin_guide_accessible(client):
    response=client.post("/login",data={"identifier":"admin","password":"admin"},follow_redirects=True)
    assert response.status_code==200
    guide=client.get("/admin/guide")
    assert guide.status_code==200
    assert "دليل الإدارة" in guide.get_data(as_text=True)
    assert "التحصيل" in guide.get_data(as_text=True)

def test_settlements_page_and_admin_guide(client):
    login(client)
    settlement=client.get("/operations/settlements")
    assert settlement.status_code==200
    body=settlement.get_data(as_text=True)
    assert "العهد وإخلاء العهدة" in body
    assert "حساب العهدة" in body
    assert body.count("دليل الإدارة") >= 1

def test_sidebar_contains_all_major_sections_and_report_links(client):
    login(client)
    body=client.get("/").get_data(as_text=True)
    for text_value in ["الرئيسية","البوابة والتحصيل","البيانات الأساسية","الإدارة والموظفون","المحاسبة والمالية","التشغيل المالي","التقارير","الإعدادات"]:
        assert text_value in body
    for url in ["/reports/daily","/reports/weekly","/reports/monthly","/reports/clients","/reports/vehicles","/reports/employees","/reports/expenses","/reports/income-expenses","/reports/trial-balance"]:
        assert url in body
    assert 'class="nav-count"' in body
    assert 'class="nav-chevron bi bi-chevron-down"' in body
