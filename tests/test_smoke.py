from decimal import Decimal
import pytest
from app.models import Account, VehicleType, JournalEntry, JournalLine
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
    response=client.post("/login",data={"username":"admin","password":"wrong"},follow_redirects=True)
    assert "بيانات الدخول غير صحيحة" in response.get_data(as_text=True)


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


def test_employee_has_separate_account_and_cashbox(app):
    with app.app_context():
        from app.models import Employee
        employee=db.session.query(Employee).filter_by(active=True).order_by(Employee.id).first()
        assert employee is not None
        assert employee.account_id is not None
        assert employee.cashbox_account_id is not None
        assert employee.account_id != employee.cashbox_account_id
        assert employee.account.is_group is False
        assert employee.cashbox_account.is_group is False
        assert employee.account.parent_id != employee.cashbox_account.parent_id
        assert employee.cashbox_account.parent.system_key == "collector_root"
        assert employee.account.parent.system_key == "employee_accounts_root"
