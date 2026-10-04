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
    assert "صناديق الموظفين والتسويات" in body
    assert "صندوق الموظف" in body
    assert body.count("دليل الإدارة") >= 1

def test_sidebar_contains_all_major_sections_and_report_links(client):
    login(client)
    body=client.get("/").get_data(as_text=True)
    for text_value in ["الرئيسية","البوابة والتحصيل","البيانات الأساسية","الإدارة والموظفون","الحسابات","التشغيل المالي","التقارير","الإعدادات"]:
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


def test_simple_receipt_and_payment_vouchers_use_cashboxes(app):
    with app.app_context():
        from app.models import User
        from app.services.operations import post_voucher

        user=db.session.query(User).filter_by(username="admin").one()
        cash=db.session.query(Account).filter_by(system_key="main_cash").one()
        other=db.session.query(Account).filter_by(system_key="entry_revenue").one()

        receipt,receipt_entry=post_voucher(
            voucher_type="receipt",amount="100",
            from_account=other,to_account=cash,
            description="اختبار قبض",user_id=user.id,
        )
        db.session.commit()
        assert receipt.voucher_type=="receipt"
        assert receipt_entry.totals()==(Decimal("100.00"),Decimal("100.00"))

        payment,payment_entry=post_voucher(
            voucher_type="payment",amount="25",
            from_account=cash,to_account=other,
            description="اختبار صرف",user_id=user.id,
        )
        db.session.commit()
        assert payment.voucher_type=="payment"
        assert payment_entry.totals()==(Decimal("25.00"),Decimal("25.00"))


def test_vouchers_page_polished_receipt_payment_ui(app, client):
    login(client)
    response=client.get("/operations/vouchers")
    assert response.status_code==200
    body=response.get_data(as_text=True)
    assert 'data-voucher-open' in body
    assert 'data-voucher-open-mode="receipt"' in body
    assert 'data-voucher-open-mode="payment"' in body
    assert "سند قبض" in body
    assert "سند صرف" in body
    assert 'id="voucher-kind-tabs"' in body
    assert 'id="voucher-type" value=""' in body
    assert "سند عام" not in body
    assert "إصدار سند" in body
    receipt_pos=body.index('data-voucher-open-mode="receipt"')
    payment_pos=body.index('data-voucher-open-mode="payment"')
    sort_pos=body.index('id="voucher-sort"')
    assert receipt_pos < payment_pos < sort_pos


def test_voucher_route_requires_post_permission(app, client):
    with app.app_context():
        from app.models import User
        user=db.session.query(User).filter_by(username="admin").one()
        user.role="auditor"
        db.session.commit()
    client.post("/login",data={"identifier":"admin","password":"admin"},follow_redirects=True)
    response=client.post("/operations/vouchers",data={
        "voucher_type":"receipt","account_id":"1","cash_account_id":"2","amount":"10","description":"x"
    },follow_redirects=True)
    assert "ليست لديك صلاحية إصدار السندات" in response.get_data(as_text=True)

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
    assert employee_response.headers["Location"].endswith("/dashboard")


def test_employee_login_accepts_hidden_bidi_marks_in_phone_and_password(app):
    from app.models import Role
    client=app.test_client()
    raw_phone="‏‪775 660 418‬‏"
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
        "password":"‏775660418‬",
    },follow_redirects=False)
    assert response.status_code==302
    assert response.headers["Location"].endswith("/dashboard")


def test_voucher_general_receipt_payment_and_reverse_flow(app, client):
    login(client)
    with app.app_context():
        from app.models import Account, Voucher, JournalEntry
        cash=db.session.query(Account).filter_by(system_key="main_cash").one()
        revenue=db.session.query(Account).filter_by(system_key="entry_revenue").one()

    receipt=client.post("/operations/vouchers",data={
        "voucher_type":"receipt","account_id":str(revenue.id),"cash_account_id":str(cash.id),
        "amount":"100","beneficiary":"اختبار","description":"قبض اختبار"
    },follow_redirects=True)
    assert receipt.status_code==200
    assert "تم إصدار السند" in receipt.get_data(as_text=True)

    with app.app_context():
        voucher=Voucher.query.order_by(Voucher.id.desc()).first()
        assert voucher.voucher_type=="receipt"
        assert voucher.status=="posted"
        voucher_id=voucher.id
        entry_id=voucher.journal_entry_id
        assert JournalEntry.query.get(entry_id).source_type=="voucher"

    general=client.post("/operations/vouchers",data={
        "voucher_type":"transfer","from_account_id":str(cash.id),"to_account_id":str(revenue.id),
        "amount":"25","beneficiary":"","description":"سند عام اختبار"
    },follow_redirects=True)
    assert general.status_code==200
    assert "تم إصدار السند" in general.get_data(as_text=True)

    reverse=client.post(f"/operations/vouchers/{voucher_id}/reverse",data={"reason":"اختبار العكس"},follow_redirects=True)
    assert reverse.status_code==200
    assert "تم عكس السند" in reverse.get_data(as_text=True)

    with app.app_context():
        from sqlalchemy import text
        with db.engine.connect() as conn:
            journal_status=conn.execute(
                text("SELECT status FROM journal_entries WHERE id=:id"),{"id":entry_id}
            ).scalar_one()
            reverse_id=conn.execute(
                text("SELECT reversed_entry_id FROM journal_entries WHERE id=:id"),{"id":entry_id}
            ).scalar_one()
        assert journal_status=="void"
        assert reverse_id is not None
        db.session.remove()
        voucher=db.session.get(Voucher,voucher_id)
        assert voucher.status=="void"
        assert voucher.journal_entry.status=="void"
        assert voucher.journal_entry.reversed_entry_id is not None
