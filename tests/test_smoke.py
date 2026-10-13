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

def test_user_management_rejects_invalid_roles_and_self_role_changes(app, client):
    with app.app_context():
        target=User(username="role_target",full_name="مستخدم اختبار",role="collector",active=True)
        target.set_password("test-password")
        db.session.add(target)
        db.session.commit()
        target_id=target.id
        admin_id=User.query.filter_by(username="admin").one().id

    login(client)
    invalid_role=client.post(f"/admin/users/{target_id}/edit",data={
        "username":"role_target",
        "full_name":"مستخدم اختبار",
        "phone":"",
        "role":"superadmin",
        "employee_id":"",
        "password":"",
    },follow_redirects=True)
    assert invalid_role.status_code==200
    assert "الدور المحدد غير صالح" in invalid_role.get_data(as_text=True)

    self_demotion=client.post(f"/admin/users/{admin_id}/edit",data={
        "username":"admin",
        "full_name":"مدير النظام",
        "phone":"",
        "role":"collector",
        "employee_id":"",
        "password":"",
    },follow_redirects=True)
    assert self_demotion.status_code==200
    assert "لا يمكنك تغيير دور حسابك الحالي" in self_demotion.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(User,target_id).role=="collector"
        assert db.session.get(User,admin_id).role=="admin"


def test_manager_cannot_grant_privileged_roles_or_manage_admin_accounts(app):
    with app.app_context():
        manager=User(username="manager_guard_test",full_name="مدير اختبار",role="manager",active=True)
        manager.set_password("manager-password")
        target=User(username="collector_guard_test",full_name="متحصل اختبار",role="collector",active=True)
        target.set_password("collector-password")
        protected_admin=User(username="admin_guard_test",full_name="مدير نظام محمي",role="admin",active=True)
        protected_admin.set_password("admin-password")
        db.session.add_all([manager,target,protected_admin])
        db.session.commit()
        target_id=target.id
        protected_admin_id=protected_admin.id

    manager_client=app.test_client()
    response=manager_client.post("/login",data={
        "identifier":"manager_guard_test","password":"manager-password"
    },follow_redirects=False)
    assert response.status_code==302

    escalation=manager_client.post(f"/admin/users/{target_id}/edit",data={
        "username":"collector_guard_test",
        "full_name":"متحصل اختبار",
        "phone":"",
        "role":"admin",
        "employee_id":"",
        "password":"",
    },follow_redirects=True)
    assert escalation.status_code==200
    assert "لا يمكنك منح صلاحية مدير أو مدير النظام" in escalation.get_data(as_text=True)

    protected_edit=manager_client.get(f"/admin/users/{protected_admin_id}/edit")
    assert protected_edit.status_code==403
    protected_permissions=manager_client.get(f"/admin/users/{protected_admin_id}/permissions")
    assert protected_permissions.status_code==403

    manager_client.post(f"/admin/users/{protected_admin_id}/toggle",follow_redirects=True)
    with app.app_context():
        assert db.session.get(User,target_id).role=="collector"
        protected=db.session.get(User,protected_admin_id)
        assert protected.role=="admin"
        assert protected.active is True


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






def test_report_export_permission_alone_does_not_grant_view(app):
    from app.models import Permission, UserPermission
    from datetime import datetime
    from zoneinfo import ZoneInfo

    with app.app_context():
        export_only=User(username="report_export_only",full_name="تصدير فقط",role="collector",active=True)
        export_only.set_password("report-password")
        db.session.add(export_only)
        db.session.flush()
        export_perm=Permission.query.filter_by(key="reports.export").one()
        db.session.add(UserPermission(user_id=export_only.id,permission_id=export_perm.id,granted=True))
        db.session.commit()

    today=datetime.now(ZoneInfo("Asia/Aden")).date().isoformat()
    client=app.test_client()
    logged=client.post("/login",data={
        "identifier":"report_export_only","password":"report-password"
    },follow_redirects=False)
    assert logged.status_code==302
    assert client.get("/reports/").status_code==403
    assert client.get(f"/reports/gate.csv?start={today}&end={today}").status_code==403


def test_report_view_permission_does_not_grant_print_or_csv_export(app):
    from app.models import Permission, UserPermission
    from datetime import datetime
    from zoneinfo import ZoneInfo

    with app.app_context():
        viewer=User(username="report_view_only",full_name="عرض فقط",role="collector",active=True)
        viewer.set_password("report-password")
        db.session.add(viewer)
        db.session.flush()
        view_perm=Permission.query.filter_by(key="reports.view").one()
        db.session.add(UserPermission(user_id=viewer.id,permission_id=view_perm.id,granted=True))
        db.session.commit()

    today=datetime.now(ZoneInfo("Asia/Aden")).date().isoformat()
    client=app.test_client()
    logged=client.post("/login",data={
        "identifier":"report_view_only","password":"report-password"
    },follow_redirects=False)
    assert logged.status_code==302
    assert client.get("/reports/").status_code==200
    report=client.get(f"/reports/gate?start={today}&end={today}")
    assert report.status_code==200
    body=report.get_data(as_text=True)
    assert 'onclick="window.print()"' not in body
    assert "gate.csv" not in body
    assert client.get(f"/reports/gate.csv?start={today}&end={today}").status_code==403



def test_journal_numbers_are_allocated_uniquely_under_concurrency(app):
    from concurrent.futures import ThreadPoolExecutor
    from app.services.accounting import next_number

    def allocate_number(_):
        with app.app_context():
            try:
                number=next_number("PAR")
                db.session.commit()
                return number
            except Exception:
                db.session.rollback()
                raise
            finally:
                db.session.remove()

    # Separate Flask/SQLAlchemy sessions simulate simultaneous web requests.
    with ThreadPoolExecutor(max_workers=4) as pool:
        numbers=list(pool.map(allocate_number,range(24)))

    assert len(numbers)==24
    assert len(set(numbers))==24
    suffixes=sorted(int(number.rsplit("-",1)[1]) for number in numbers)
    assert suffixes==list(range(suffixes[0],suffixes[0]+24))


def test_journal_number_counter_rolls_back_with_the_transaction(app):
    from app.models import JournalNumberCounter
    from app.services.accounting import next_number

    with app.app_context():
        counter=db.session.get(JournalNumberCounter,1)
        assert counter is not None
        initial=counter.last_value

        first=next_number("ROLLBACK")
        second=next_number("ROLLBACK")
        assert int(second.rsplit("-",1)[1])==int(first.rsplit("-",1)[1])+1
        db.session.rollback()

        db.session.expire_all()
        counter=db.session.get(JournalNumberCounter,1)
        assert counter.last_value==initial
        after_rollback=next_number("ROLLBACK")
        assert after_rollback==first
        db.session.rollback()



def test_account_tree_edit_rejects_direct_and_indirect_cycles(app, client):
    login(client)
    with app.app_context():
        assets_root=Account.query.filter_by(system_key="root_assets").one()
        parent=Account(
            code="990CYC01", name="مجموعة اختبار الدورة", account_type="asset",
            parent_id=assets_root.id, is_group=True, active=True, allow_manual_posting=False,
        )
        db.session.add(parent)
        db.session.flush()
        child=Account(
            code="990CYC02", name="فرع مجموعة اختبار الدورة", account_type="asset",
            parent_id=parent.id, is_group=True, active=True, allow_manual_posting=False,
        )
        db.session.add(child)
        db.session.flush()
        grandchild=Account(
            code="990CYC03", name="الفرع المتداخل لاختبار الدورة", account_type="asset",
            parent_id=child.id, is_group=True, active=True, allow_manual_posting=False,
        )
        db.session.add(grandchild)
        db.session.commit()
        parent_id, root_id = parent.id, assets_root.id
        child_id, grandchild_id = child.id, grandchild.id
        original_name=parent.name

    edit_url=f"/accounting/accounts/{parent_id}/edit"
    edit_page=client.get(edit_url)
    assert edit_page.status_code==200
    select_html=edit_page.get_data(as_text=True).split('<select name="parent_id"',1)[1].split("</select>",1)[0]
    assert f'value="{child_id}"' not in select_html
    assert f'value="{grandchild_id}"' not in select_html

    # Attempting to move a group below a nested descendant must be blocked server-side,
    # even though the browser normally hides that invalid option.
    nested_cycle=client.post(edit_url,data={
        "name":original_name,
        "parent_id":str(grandchild_id),
        "active":"1",
    })
    assert nested_cycle.status_code==200
    assert "لا يمكن نقل الحساب إلى نفسه أو إلى أحد فروعه" in nested_cycle.get_data(as_text=True)

    direct_cycle=client.post(edit_url,data={
        "name":original_name,
        "parent_id":str(parent_id),
        "active":"1",
    })
    assert direct_cycle.status_code==200
    assert "لا يمكن نقل الحساب إلى نفسه أو إلى أحد فروعه" in direct_cycle.get_data(as_text=True)

    with app.app_context():
        unchanged=db.session.get(Account,parent_id)
        assert unchanged.parent_id==root_id
        assert unchanged.name==original_name

def test_collector_dashboard_shows_employee_cashbox_balance(app):
    from datetime import date
    from app.services.accounts import ensure_employee_account, ensure_employee_cashbox

    with app.app_context():
        admin=User.query.filter_by(username="admin").one()
        employee=Employee(code="EMP-CASHBOX-DASH-01",full_name="اختبار صندوق الموظف",
                          phone="777000321",job_title="متحصل",active=True)
        db.session.add(employee)
        db.session.flush()
        general_account=ensure_employee_account(employee)
        cashbox_account=ensure_employee_cashbox(employee)
        collector=User(username="cashbox_dashboard_test",full_name=employee.full_name,
                       role="collector",active=True,employee_id=employee.id)
        collector.set_password("cashbox-test-password")
        db.session.add(collector)
        db.session.flush()
        revenue=db.session.query(Account).filter_by(system_key="entry_revenue").one()
        create_posted_entry(
            description="اختبار رصيد صندوق الموظف والحساب العام",
            entry_date=date.today(),created_by_id=admin.id,
            lines=[
                {"account":cashbox_account,"debit":Decimal("321"),"credit":Decimal("0")},
                {"account":general_account,"debit":Decimal("9000"),"credit":Decimal("0")},
                {"account":revenue,"debit":Decimal("0"),"credit":Decimal("9321")},
            ],prefix="CBX")
        db.session.commit()

    collector_client=app.test_client()
    logged_in=collector_client.post("/login",data={
        "identifier":"cashbox_dashboard_test","password":"cashbox-test-password"
    },follow_redirects=False)
    assert logged_in.status_code==302
    response=collector_client.get("/collector")
    assert response.status_code==200
    body=response.get_data(as_text=True)
    assert 'class="collector-mini-stat cashbox"' in body
    assert "صندوق الموظف</span><strong>321</strong>" in body
    assert "صندوق الموظف</span><strong>9,000</strong>" not in body

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
    assert "سند عام" in body
    assert "سند قبض" in body
    assert "سند صرف" in body
    assert 'id="voucher-kind-tabs"' in body
    assert 'id="voucher-type" value=""' in body
    assert "إصدار سند" in body
    assert "voucher-toolbar-btn general" in body
    assert "voucher-toolbar-btn receipt" in body
    assert "voucher-toolbar-btn payment" in body
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


def test_agent_lease_creation_accrual_and_collection(app, client):
    from datetime import date
    from app.models import Agent, AgentLease, AgentRent

    login(client)
    with app.app_context():
        agent=Agent(code="LEASE-TEST-01",name="وكيل اختبار عقد الإيجار",phone="777000111",active=True)
        db.session.add(agent)
        db.session.commit()
        agent_id=agent.id

    contracts_page=client.get("/operations/leases")
    assert contracts_page.status_code==200
    page_body=contracts_page.get_data(as_text=True)
    assert 'data-lease-open' in page_body
    assert 'id="lease-form"' in page_body
    assert 'id="lease-cards"' in page_body
    assert "إضافة عقد جديد" in page_body

    start=date.today().replace(day=1)
    response=client.post("/operations/leases",data={
        "agent_id":str(agent_id),
        "name":"إيجار اختبار سنوي",
        "monthly_amount":"1500",
        "starts_on":start.isoformat(),
        "ends_on":"",
        "due_day":"5",
    },follow_redirects=True)
    assert response.status_code==200
    assert "تم إنشاء عقد الإيجار للوكيل" in response.get_data(as_text=True)

    with app.app_context():
        lease=AgentLease.query.filter_by(agent_id=agent_id,name="إيجار اختبار سنوي").one()
        lease_id=lease.id
        assert lease.monthly_amount==Decimal("1500.00")
        assert lease.starts_on==start
        assert lease.due_day==5
        assert lease.agent.account_id is not None
        assert lease.agent.account.is_group is False
        assert lease.active is True

    rents_page=client.get(f"/operations/rents?lease_id={lease_id}")
    assert rents_page.status_code==200
    rents_body=rents_page.get_data(as_text=True)
    assert f'value="{lease_id}" data-agent="{agent_id}"' in rents_body
    assert 'id="rent-month" type="month"' in rents_body

    # Browser month controls submit YYYY-MM; the route must accept this format.
    accrual=client.post(f"/operations/leases/{lease_id}/charge",data={
        "rent_month":start.strftime("%Y-%m"),
        "base_amount":"1500",
        "discount":"100",
        "addition":"25",
    },follow_redirects=True)
    assert accrual.status_code==200
    assert "تم إثبات استحقاق الإيجار" in accrual.get_data(as_text=True)

    with app.app_context():
        rent=AgentRent.query.filter_by(lease_id=lease_id,rent_month=start).one()
        rent_id=rent.id
        agent_account_id=rent.agent.account_id
        cash_id=db.session.query(Account).filter_by(system_key="main_cash").one().id
        assert rent.amount==Decimal("1425.00")
        assert rent.status=="unpaid"
        accrual_entry=JournalEntry.query.get(rent.journal_entry_id)
        accrual_lines={line.account_id:line for line in accrual_entry.lines}
        assert accrual_lines[agent_account_id].debit==Decimal("1425.00")
        assert accrual_lines[db.session.query(Account).filter_by(system_key="rent_revenue").one().id].credit==Decimal("1425.00")

    payment=client.post(f"/operations/rents/{rent_id}/pay",data={},follow_redirects=True)
    assert payment.status_code==200
    assert "تم تحصيل الإيجار" in payment.get_data(as_text=True)

    with app.app_context():
        rent=db.session.get(AgentRent,rent_id)
        assert rent.status=="paid"
        assert rent.payment_journal_id is not None
        payment_entry=__import__("app.models",fromlist=["JournalEntry"]).JournalEntry.query.get(rent.payment_journal_id)
        payment_lines={line.account_id:line for line in payment_entry.lines}
        assert payment_lines[cash_id].debit==Decimal("1425.00")
        assert payment_lines[agent_account_id].credit==Decimal("1425.00")

    # Invalid contracts should show a useful error and must not be saved.
    invalid=client.post("/operations/leases",data={
        "agent_id":str(agent_id),
        "name":"عقد غير صالح",
        "monthly_amount":"0",
        "starts_on":start.isoformat(),
        "ends_on":"",
        "due_day":"5",
    },follow_redirects=True)
    assert invalid.status_code==200
    assert "المبلغ الشهري يجب أن يكون أكبر من صفر" in invalid.get_data(as_text=True)
    with app.app_context():
        assert AgentLease.query.filter_by(agent_id=agent_id,name="عقد غير صالح").count()==0


def test_receipt_to_main_cash_handles_legacy_account_tree(app, client):
    login(client)
    with app.app_context():
        from app.services.operations import is_cash_account

        cash = db.session.query(Account).filter_by(system_key="main_cash").one()
        revenue = db.session.query(Account).filter_by(system_key="entry_revenue").one()
        assets_root = db.session.query(Account).filter_by(system_key="root_assets").one()

        # Simulate an older database where the system cash account's parent
        # differs from the current seed hierarchy.
        cash.parent_id = assets_root.id
        db.session.commit()
        cash_id, revenue_id = cash.id, revenue.id
        assert is_cash_account(cash) is True

    page = client.get("/operations/vouchers")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    cash_picker_start = body.index('data-name="cash_account_id"')
    transfer_picker_start = body.index('data-name="from_account_id"', cash_picker_start)
    assert f'data-account-id="{cash_id}"' in body[cash_picker_start:transfer_picker_start]

    response = client.post("/operations/vouchers", data={
        "voucher_type": "receipt",
        "account_id": str(revenue_id),
        "cash_account_id": str(cash_id),
        "amount": "65",
        "beneficiary": "اختبار الصندوق الرئيسي",
        "description": "اختبار قبض للصندوق الرئيسي مع اختلاف شجرة الحسابات",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert "تم إصدار السند" in response.get_data(as_text=True)
    assert "يجب أن يصب في حساب صندوق" not in response.get_data(as_text=True)

    with app.app_context():
        from app.models import Voucher

        voucher = Voucher.query.order_by(Voucher.id.desc()).first()
        assert voucher.voucher_type == "receipt"
        assert voucher.status == "posted"
        assert voucher.from_account_id == revenue_id
        assert voucher.to_account_id == cash_id
        lines = {line.account_id: line for line in voucher.journal_entry.lines}
        assert lines[cash_id].debit == Decimal("65.00")
        assert lines[revenue_id].credit == Decimal("65.00")


def test_voucher_general_receipt_payment_and_reverse_flow(app, client):
    login(client)
    with app.app_context():
        from app.models import Account, Voucher, JournalEntry
        from app.services.accounting import account_balance
        cash=db.session.query(Account).filter_by(system_key="main_cash").one()
        revenue=db.session.query(Account).filter_by(system_key="entry_revenue").one()
        cash_id, revenue_id = cash.id, revenue.id
        cash_before = account_balance(cash_id)
        revenue_before = account_balance(revenue_id)

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
        assert journal_status=="posted"
        assert reverse_id is not None
        db.session.remove()
        voucher=db.session.get(Voucher,voucher_id)
        assert voucher.status=="void"
        assert voucher.journal_entry.status=="posted"
        assert voucher.journal_entry.reversed_entry_id is not None
        # After reversing the receipt, only the separate 25-unit transfer remains.
        assert account_balance(cash_id) == cash_before - Decimal("25.00")
        assert account_balance(revenue_id) == revenue_before + Decimal("25.00")



def test_audit_log_records_context_and_ignores_untrusted_forwarded_ip(app):
    from flask_login import login_user
    from app.models import AuditLog
    from app.services.audit import audit

    with app.app_context():
        admin = User.query.filter_by(username="admin").one()
        with app.test_request_context(
            "/audit-test/path?token=must-not-be-stored",
            method="POST",
            headers={
                "X-Forwarded-For": "198.51.100.222",
                "User-Agent": "KareemAuditRegression/1.0",
            },
            environ_base={"REMOTE_ADDR": "192.0.2.17"},
        ):
            login_user(admin)
            audit("test_context", "audit_test", 987, "context metadata")
            db.session.commit()

        row = AuditLog.query.filter_by(action="test_context", entity_id=987).one()
        assert row.actor_username == "admin"
        assert row.actor_name == "مدير النظام"
        assert row.request_method == "POST"
        assert row.request_path == "/audit-test/path"
        assert "token" not in row.request_path
        assert row.user_agent == "KareemAuditRegression/1.0"
        assert row.ip_address == "192.0.2.17"


def test_audit_log_filters_search_and_pagination(app, client):
    from app.models import AuditLog

    with app.app_context():
        admin = User.query.filter_by(username="admin").one()
        entries = []
        for index in range(53):
            entries.append(AuditLog(
                user_id=admin.id,
                actor_username=admin.username,
                actor_name=admin.full_name,
                action="create" if index < 52 else "update",
                entity_type="client",
                entity_id=index + 1,
                details="needle — عميل اختبار" if index == 17 else f"سجل اختبار {index + 1}",
                ip_address="192.0.2.10",
                request_method="POST",
                request_path="/master-data/clients",
                user_agent="AuditPaginationTest/1.0",
            ))
        db.session.add_all(entries)
        db.session.commit()

    login(client)
    first_page = client.get("/admin/audit?action=create&entity_type=client&per_page=25")
    assert first_page.status_code == 200
    first_body = first_page.get_data(as_text=True)
    assert first_body.count('class="audit-row"') == 25
    assert "52" in first_body
    assert "page=2" in first_body
    assert "إنشاء سجل" in first_body

    filtered = client.get("/admin/audit?q=needle&action=create&entity_type=client")
    assert filtered.status_code == 200
    filtered_body = filtered.get_data(as_text=True)
    assert filtered_body.count('class="audit-row"') == 1
    assert "needle" in filtered_body
    assert "192.0.2.10" in filtered_body
