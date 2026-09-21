"""initial wholesale market schema"""
from alembic import op
import sqlalchemy as sa

revision="0001_initial"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("accounts",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("code",sa.String(50),nullable=False,unique=True),
        sa.Column("name",sa.String(180),nullable=False),
        sa.Column("account_type",sa.String(30),nullable=False),
        sa.Column("parent_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT")),
        sa.Column("is_group",sa.Boolean(),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),
        sa.Column("allow_manual_posting",sa.Boolean(),nullable=False),
        sa.Column("system_key",sa.String(80),unique=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.CheckConstraint("NOT (is_group = TRUE AND allow_manual_posting = TRUE)",name="ck_group_not_postable"))
    op.create_index("ix_accounts_code","accounts",["code"])

    op.create_table("employees",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("code",sa.String(30),nullable=False,unique=True),
        sa.Column("full_name",sa.String(160),nullable=False),sa.Column("phone",sa.String(30)),
        sa.Column("job_title",sa.String(100)),sa.Column("monthly_salary",sa.Numeric(18,2),nullable=False),
        sa.Column("hire_date",sa.Date()),sa.Column("active",sa.Boolean(),nullable=False),
        sa.Column("account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="SET NULL"),unique=True),
        sa.Column("payroll_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="SET NULL"),unique=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("users",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("username",sa.String(80),nullable=False,unique=True),
        sa.Column("full_name",sa.String(160),nullable=False),sa.Column("phone",sa.String(30),unique=True),
        sa.Column("password_hash",sa.String(255),nullable=False),sa.Column("role",sa.String(30),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("employee_id",sa.Integer(),sa.ForeignKey("employees.id",ondelete="SET NULL")),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))
    op.create_index("ix_users_username","users",["username"])
    op.create_index("ix_users_role","users",["role"])

    op.create_table("agents",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("code",sa.String(30),nullable=False,unique=True),
        sa.Column("name",sa.String(160),nullable=False),sa.Column("phone",sa.String(30)),sa.Column("notes",sa.Text()),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="SET NULL"),unique=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("clients",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("code",sa.String(30),nullable=False,unique=True),
        sa.Column("name",sa.String(160),nullable=False),sa.Column("phone",sa.String(30)),sa.Column("address",sa.String(255)),
        sa.Column("notes",sa.Text()),sa.Column("active",sa.Boolean(),nullable=False),
        sa.Column("account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="SET NULL"),unique=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("client_agents",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("client_id",sa.Integer(),sa.ForeignKey("clients.id",ondelete="CASCADE"),nullable=False),
        sa.Column("agent_id",sa.Integer(),sa.ForeignKey("agents.id",ondelete="CASCADE"),nullable=False),
        sa.Column("priority",sa.Integer(),nullable=False),sa.Column("active",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.UniqueConstraint("client_id","agent_id",name="uq_client_agent"))

    op.create_table("vehicle_types",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("name",sa.String(80),nullable=False,unique=True),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("is_system",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("vehicles",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("plate_number",sa.String(40),nullable=False),
        sa.Column("plate_separator",sa.String(40)),sa.Column("plate_letters",sa.String(40)),
        sa.Column("vehicle_type_id",sa.Integer(),sa.ForeignKey("vehicle_types.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("client_id",sa.Integer(),sa.ForeignKey("clients.id",ondelete="SET NULL")),sa.Column("notes",sa.Text()),
        sa.Column("active",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.UniqueConstraint("plate_number","plate_separator",name="uq_vehicle_plate"))
    op.create_index("ix_vehicle_plate_search","vehicles",["plate_number","plate_separator"])

    op.create_table("vehicle_agents",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("vehicle_id",sa.Integer(),sa.ForeignKey("vehicles.id",ondelete="CASCADE"),nullable=False),
        sa.Column("agent_id",sa.Integer(),sa.ForeignKey("agents.id",ondelete="CASCADE"),nullable=False),
        sa.Column("last_used_at",sa.DateTime(timezone=True)),sa.Column("active",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.UniqueConstraint("vehicle_id","agent_id",name="uq_vehicle_agent"))

    op.create_table("journal_entries",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("number",sa.String(40),nullable=False,unique=True),
        sa.Column("entry_date",sa.Date(),nullable=False),sa.Column("description",sa.String(500),nullable=False),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("source_type",sa.String(50),nullable=False),
        sa.Column("source_id",sa.Integer()),sa.Column("created_by_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("posted_at",sa.DateTime(timezone=True)),sa.Column("reversed_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="SET NULL")),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.CheckConstraint("status IN ('posted','draft','void')",name="ck_journal_status"))
    op.create_index("ix_journal_entries_number","journal_entries",["number"])
    op.create_index("ix_journal_entries_entry_date","journal_entries",["entry_date"])

    op.create_table("journal_lines",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="CASCADE"),nullable=False),
        sa.Column("account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("description",sa.String(500)),sa.Column("debit",sa.Numeric(18,2),nullable=False),
        sa.Column("credit",sa.Numeric(18,2),nullable=False),sa.Column("reference",sa.String(100)),
        sa.CheckConstraint("debit >= 0 AND credit >= 0",name="ck_line_non_negative"),
        sa.CheckConstraint("(debit = 0) <> (credit = 0)",name="ck_line_one_side"))

    op.create_table("vouchers",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("number",sa.String(40),nullable=False,unique=True),
        sa.Column("voucher_type",sa.String(30),nullable=False),sa.Column("voucher_date",sa.Date(),nullable=False),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),sa.Column("from_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT")),
        sa.Column("to_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT")),
        sa.Column("beneficiary",sa.String(180)),sa.Column("description",sa.String(500),nullable=False),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("journal_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="RESTRICT")),
        sa.Column("created_by_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("shifts",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("collector_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("shift_name",sa.String(50),nullable=False),sa.Column("opened_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("closed_at",sa.DateTime(timezone=True)),sa.Column("opening_balance",sa.Numeric(18,2),nullable=False),
        sa.Column("closing_balance",sa.Numeric(18,2)),sa.Column("settlement_journal_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="SET NULL")),
        sa.Column("status",sa.String(20),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.CheckConstraint("status IN ('open','pending','closed')",name="ck_shift_status"))

    op.create_table("gate_transactions",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("receipt_number",sa.String(50),nullable=False,unique=True),
        sa.Column("transaction_date",sa.DateTime(timezone=True),nullable=False),sa.Column("direction",sa.String(10),nullable=False),
        sa.Column("vehicle_id",sa.Integer(),sa.ForeignKey("vehicles.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("client_id",sa.Integer(),sa.ForeignKey("clients.id",ondelete="SET NULL")),
        sa.Column("agent_id",sa.Integer(),sa.ForeignKey("agents.id",ondelete="SET NULL")),
        sa.Column("collector_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("shift_id",sa.Integer(),sa.ForeignKey("shifts.id",ondelete="RESTRICT")),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),sa.Column("payment_method",sa.String(20),nullable=False),
        sa.Column("notes",sa.String(500)),sa.Column("journal_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="RESTRICT")),
        sa.Column("counted_for_work",sa.Boolean(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.CheckConstraint("amount >= 0",name="ck_gate_amount_nonnegative"),
        sa.CheckConstraint("direction IN ('entry','exit')",name="ck_gate_direction"))
    op.create_index("ix_gate_receipt_number","gate_transactions",["receipt_number"])
    op.create_index("ix_gate_transaction_date","gate_transactions",["transaction_date"])
    op.create_index("ix_gate_collector_date","gate_transactions",["collector_id","transaction_date"])

    op.create_table("settlements",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("number",sa.String(50),nullable=False,unique=True),
        sa.Column("settlement_date",sa.Date(),nullable=False),sa.Column("source_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("target_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),sa.Column("description",sa.String(500),nullable=False),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("requested_by_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("approved_by_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL")),sa.Column("approved_at",sa.DateTime(timezone=True)),
        sa.Column("journal_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="RESTRICT")),
        sa.Column("shift_id",sa.Integer(),sa.ForeignKey("shifts.id",ondelete="SET NULL")),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("agent_leases",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("agent_id",sa.Integer(),sa.ForeignKey("agents.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("name",sa.String(120),nullable=False),sa.Column("monthly_amount",sa.Numeric(18,2),nullable=False),
        sa.Column("starts_on",sa.Date(),nullable=False),sa.Column("ends_on",sa.Date()),sa.Column("due_day",sa.Integer(),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("agent_rents",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("agent_id",sa.Integer(),sa.ForeignKey("agents.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("lease_id",sa.Integer(),sa.ForeignKey("agent_leases.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("rent_month",sa.Date(),nullable=False),sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("journal_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="SET NULL")),
        sa.Column("payment_journal_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="SET NULL")),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.UniqueConstraint("agent_id","rent_month",name="uq_agent_rent_month"))

    op.create_table("payroll_runs",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("payroll_month",sa.Date(),nullable=False,unique=True),
        sa.Column("status",sa.String(20),nullable=False),sa.Column("journal_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="SET NULL")),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

    op.create_table("payroll_lines",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("payroll_run_id",sa.Integer(),sa.ForeignKey("payroll_runs.id",ondelete="CASCADE"),nullable=False),
        sa.Column("employee_id",sa.Integer(),sa.ForeignKey("employees.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("gross_amount",sa.Numeric(18,2),nullable=False),sa.Column("deductions",sa.Numeric(18,2),nullable=False),sa.Column("net_amount",sa.Numeric(18,2),nullable=False))

    op.create_table("permissions",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("key",sa.String(120),nullable=False,unique=True),
        sa.Column("name",sa.String(180),nullable=False),sa.Column("group_name",sa.String(80),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))
    op.create_index("ix_permissions_key","permissions",["key"])

    op.create_table("user_permissions",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("permission_id",sa.Integer(),sa.ForeignKey("permissions.id",ondelete="CASCADE"),nullable=False),sa.Column("granted",sa.Boolean(),nullable=False),
        sa.UniqueConstraint("user_id","permission_id",name="uq_user_permission"))

    op.create_table("audit_logs",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL")),
        sa.Column("action",sa.String(80),nullable=False),sa.Column("entity_type",sa.String(80),nullable=False),
        sa.Column("entity_id",sa.Integer()),sa.Column("details",sa.Text()),sa.Column("ip_address",sa.String(64)),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))
    op.create_index("ix_audit_logs_created_at","audit_logs",["created_at"])

    op.create_table("settings",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("key",sa.String(100),nullable=False,unique=True),
        sa.Column("value",sa.Text()),sa.Column("value_type",sa.String(30),nullable=False),sa.Column("description",sa.String(255)),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False))

def downgrade():
    for table in ["settings","audit_logs","user_permissions","permissions","payroll_lines","payroll_runs","agent_rents","agent_leases","settlements","gate_transactions","shifts","vouchers","journal_lines","journal_entries","vehicle_agents","vehicles","vehicle_types","client_agents","clients","agents","users","employees","accounts"]:
        op.drop_table(table)
