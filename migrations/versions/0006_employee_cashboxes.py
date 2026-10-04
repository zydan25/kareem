"""separate employee accounts from employee cashboxes

Revision ID: 0006_employee_cashboxes
Revises: 0005_employee_fines
"""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = "0006_employee_cashboxes"
down_revision = "0005_employee_fines"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employees", sa.Column("cashbox_account_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_employees_cashbox_account_id", "employees", ["cashbox_account_id"])
    op.create_foreign_key(
        "fk_employees_cashbox_account_id_accounts",
        "employees",
        "accounts",
        ["cashbox_account_id"],
        ["id"],
        ondelete="SET NULL",
    )

    conn = op.get_bind()
    accounts = sa.table(
        "accounts",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("account_type", sa.String()),
        sa.column("parent_id", sa.Integer()),
        sa.column("is_group", sa.Boolean()),
        sa.column("active", sa.Boolean()),
        sa.column("allow_manual_posting", sa.Boolean()),
        sa.column("system_key", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    employees = sa.table(
        "employees",
        sa.column("id", sa.Integer()),
        sa.column("full_name", sa.String()),
        sa.column("account_id", sa.Integer()),
        sa.column("cashbox_account_id", sa.Integer()),
    )

    assets_id = conn.execute(sa.select(accounts.c.id).where(accounts.c.system_key == "root_assets")).scalar_one_or_none()
    cash_root_id = conn.execute(sa.select(accounts.c.id).where(accounts.c.system_key == "cash_root")).scalar_one_or_none()
    collector_root_id = conn.execute(sa.select(accounts.c.id).where(accounts.c.system_key == "collector_root")).scalar_one_or_none()

    # On a fresh database the system account tree is created by seed() after
    # migrations. There is nothing to migrate here yet.
    if assets_id is None or cash_root_id is None or collector_root_id is None:
        return

    employee_root_id = conn.execute(
        sa.select(accounts.c.id).where(accounts.c.system_key == "employee_accounts_root")
    ).scalar_one_or_none()
    if employee_root_id is None:
        conn.execute(
            accounts.insert().values(
                code="105",
                name="حسابات الموظفين",
                account_type="asset",
                parent_id=assets_id,
                is_group=True,
                active=True,
                allow_manual_posting=False,
                system_key="employee_accounts_root",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        employee_root_id = conn.execute(
            sa.select(accounts.c.id).where(accounts.c.system_key == "employee_accounts_root")
        ).scalar_one()

    # The old collector/custody branch becomes a real cashbox group.
    conn.execute(
        accounts.update()
        .where(accounts.c.id == collector_root_id)
        .values(parent_id=cash_root_id, name="صناديق الموظفين", updated_at=datetime.now(timezone.utc))
    )

    employee_rows = conn.execute(
        sa.select(employees.c.id, employees.c.full_name, employees.c.account_id)
        .order_by(employees.c.id)
    ).all()

    for employee_id, full_name, old_account_id in employee_rows:
        now = datetime.now(timezone.utc)

        if old_account_id is None:
            new_employee_code = f"105E{employee_id:06d}"
            existing_id = conn.execute(
                sa.select(accounts.c.id).where(accounts.c.code == new_employee_code)
            ).scalar_one_or_none()
            if existing_id is None:
                conn.execute(
                    accounts.insert().values(
                        code=new_employee_code,
                        name=f"حساب موظف: {full_name}",
                        account_type="asset",
                        parent_id=employee_root_id,
                        is_group=False,
                        active=True,
                        allow_manual_posting=True,
                        system_key=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                old_account_id = conn.execute(
                    sa.select(accounts.c.id).where(accounts.c.code == new_employee_code)
                ).scalar_one()
            else:
                old_account_id = existing_id
            conn.execute(
                employees.update()
                .where(employees.c.id == employee_id)
                .values(account_id=old_account_id)
            )
            # There was no historic custody account, so create a new cashbox below.
            old_account_id = None

        cashbox_id = conn.execute(
            sa.select(accounts.c.id)
            .where(
                accounts.c.parent_id == collector_root_id,
                accounts.c.name == f"صندوق موظف: {full_name}",
            )
            .limit(1)
        ).scalar_one_or_none()

        historic_account_id = conn.execute(
            sa.select(accounts.c.id)
            .where(accounts.c.id == conn.execute(
                sa.select(employees.c.account_id).where(employees.c.id == employee_id)
            ).scalar_one())
        ).scalar_one()

        # If the existing employee account is an old 102E* custody account,
        # preserve it as the cashbox and create a brand-new employee account.
        old_code = conn.execute(
            sa.select(accounts.c.code).where(accounts.c.id == historic_account_id)
        ).scalar_one()
        is_legacy_custody = bool(old_code and old_code.startswith("102E"))

        if is_legacy_custody:
            conn.execute(
                accounts.update()
                .where(accounts.c.id == historic_account_id)
                .values(
                    parent_id=collector_root_id,
                    name=f"صندوق موظف: {full_name}",
                    updated_at=now,
                )
            )
            cashbox_id = historic_account_id

            new_code = f"105E{employee_id:06d}"
            existing_employee_account = conn.execute(
                sa.select(accounts.c.id).where(accounts.c.code == new_code)
            ).scalar_one_or_none()
            if existing_employee_account is None:
                conn.execute(
                    accounts.insert().values(
                        code=new_code,
                        name=f"حساب موظف: {full_name}",
                        account_type="asset",
                        parent_id=employee_root_id,
                        is_group=False,
                        active=True,
                        allow_manual_posting=True,
                        system_key=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                existing_employee_account = conn.execute(
                    sa.select(accounts.c.id).where(accounts.c.code == new_code)
                ).scalar_one()
            conn.execute(
                employees.update()
                .where(employees.c.id == employee_id)
                .values(account_id=existing_employee_account, cashbox_account_id=cashbox_id)
            )
        else:
            # Fresh/partially initialized databases: keep the employee account,
            # ensure it is in the employee branch, then create a cashbox.
            conn.execute(
                accounts.update()
                .where(accounts.c.id == historic_account_id)
                .values(
                    parent_id=employee_root_id,
                    name=f"حساب موظف: {full_name}",
                    account_type="asset",
                    is_group=False,
                    allow_manual_posting=True,
                    updated_at=now,
                )
            )
            if cashbox_id is None:
                code = f"102E{employee_id:06d}"
                conn.execute(
                    accounts.insert().values(
                        code=code,
                        name=f"صندوق موظف: {full_name}",
                        account_type="asset",
                        parent_id=collector_root_id,
                        is_group=False,
                        active=True,
                        allow_manual_posting=True,
                        system_key=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                cashbox_id = conn.execute(
                    sa.select(accounts.c.id).where(accounts.c.code == code)
                ).scalar_one()
            conn.execute(
                employees.update()
                .where(employees.c.id == employee_id)
                .values(cashbox_account_id=cashbox_id)
            )

    # Existing standalone collector accounts are cashboxes now as well.
    conn.execute(
        accounts.update()
        .where(accounts.c.parent_id == collector_root_id)
        .where(accounts.c.name.like("عهدة متحصل:%"))
        .values(name=sa.func.replace(accounts.c.name, "عهدة متحصل:", "صندوق متحصل:"), updated_at=sa.func.now())
    )


def downgrade():
    conn = op.get_bind()
    accounts = sa.table(
        "accounts",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("parent_id", sa.Integer()),
        sa.column("system_key", sa.String()),
    )
    employees = sa.table(
        "employees",
        sa.column("id", sa.Integer()),
        sa.column("account_id", sa.Integer()),
        sa.column("cashbox_account_id", sa.Integer()),
    )

    new_employee_accounts = conn.execute(
        sa.select(accounts.c.id).where(accounts.c.code.like("105E%"))
    ).scalars().all()
    if new_employee_accounts:
        journal_lines = sa.table(
            "journal_lines",
            sa.column("account_id", sa.Integer()),
        )
        used = conn.execute(
            sa.select(sa.func.count())
            .select_from(journal_lines)
            .where(journal_lines.c.account_id.in_(new_employee_accounts))
        ).scalar_one()
        if used:
            raise RuntimeError("لا يمكن التراجع: توجد قيود مرحّلة على حسابات الموظفين الجديدة")

    root_assets_id = conn.execute(sa.select(accounts.c.id).where(accounts.c.system_key == "root_assets")).scalar_one()
    cash_root_id = conn.execute(sa.select(accounts.c.id).where(accounts.c.system_key == "cash_root")).scalar_one()
    collector_root_id = conn.execute(sa.select(accounts.c.id).where(accounts.c.system_key == "collector_root")).scalar_one()

    rows = conn.execute(
        sa.select(employees.c.id, employees.c.cashbox_account_id).where(employees.c.cashbox_account_id.is_not(None))
    ).all()
    for employee_id, cashbox_id in rows:
        conn.execute(
            employees.update()
            .where(employees.c.id == employee_id)
            .values(account_id=cashbox_id, cashbox_account_id=None)
        )

    conn.execute(
        accounts.update()
        .where(accounts.c.id == collector_root_id)
        .values(parent_id=root_assets_id, name="عهد الموظفين والمتحصلين", updated_at=sa.func.now())
    )
    conn.execute(
        accounts.delete().where(accounts.c.system_key == "employee_accounts_root")
    )

    op.drop_constraint("fk_employees_cashbox_account_id_accounts", "employees", type_="foreignkey")
    op.drop_constraint("uq_employees_cashbox_account_id", "employees", type_="unique")
    op.drop_column("employees", "cashbox_account_id")
