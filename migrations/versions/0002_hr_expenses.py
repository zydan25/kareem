"""hr, rent adjustments and expense management

Revision ID: 0002_hr_expenses
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision="0002_hr_expenses"
down_revision="0001_initial"
branch_labels=None
depends_on=None


def upgrade():
    op.add_column("employees", sa.Column("identity_number", sa.String(80), nullable=True))
    op.add_column("employees", sa.Column("identity_image", sa.String(255), nullable=True))
    op.add_column("employees", sa.Column("gender", sa.String(20), nullable=True))
    op.add_column("employees", sa.Column("employment_type", sa.String(40), nullable=True))
    op.add_column("employees", sa.Column("weekly_hours", sa.Numeric(6,2), nullable=True, server_default="48"))
    op.add_column("employees", sa.Column("work_days", sa.String(120), nullable=True, server_default="0,1,2,3,4,5"))
    op.add_column("employees", sa.Column("notes", sa.Text(), nullable=True))
    op.execute("UPDATE employees SET employment_type='دوام كامل' WHERE employment_type IS NULL")
    op.execute("UPDATE employees SET weekly_hours=48 WHERE weekly_hours IS NULL")
    op.execute("UPDATE employees SET work_days='0,1,2,3,4,5' WHERE work_days IS NULL")

    op.add_column("agent_rents", sa.Column("base_amount", sa.Numeric(18,2), nullable=True, server_default="0"))
    op.add_column("agent_rents", sa.Column("discount", sa.Numeric(18,2), nullable=True, server_default="0"))
    op.add_column("agent_rents", sa.Column("addition", sa.Numeric(18,2), nullable=True, server_default="0"))
    op.execute("UPDATE agent_rents SET base_amount=amount WHERE base_amount IS NULL")
    op.execute("UPDATE agent_rents SET discount=0 WHERE discount IS NULL")
    op.execute("UPDATE agent_rents SET addition=0 WHERE addition IS NULL")

    op.create_table(
        "employee_schedules",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("employee_id",sa.Integer(),sa.ForeignKey("employees.id",ondelete="CASCADE"),nullable=False),
        sa.Column("weekday",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("shift_name",sa.String(80),nullable=False,server_default="دوام"),
        sa.Column("start_time",sa.Time(),nullable=True),
        sa.Column("end_time",sa.Time(),nullable=True),
        sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.UniqueConstraint("employee_id","weekday","shift_name",name="uq_employee_schedule"),
    )
    op.create_index("ix_employee_schedules_employee_weekday","employee_schedules",["employee_id","weekday"])

    op.create_table(
        "expenses",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("number",sa.String(40),nullable=False,unique=True),
        sa.Column("expense_date",sa.Date(),nullable=False),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("expense_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("cash_account_id",sa.Integer(),sa.ForeignKey("accounts.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("beneficiary",sa.String(180)),
        sa.Column("description",sa.String(500),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="posted"),
        sa.Column("journal_entry_id",sa.Integer(),sa.ForeignKey("journal_entries.id",ondelete="RESTRICT")),
        sa.Column("created_by_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),server_default=sa.text("CURRENT_TIMESTAMP"),nullable=False),
    )
    op.create_index("ix_expenses_number","expenses",["number"])
    op.create_index("ix_expenses_date","expenses",["expense_date"])


def downgrade():
    op.drop_index("ix_expenses_date",table_name="expenses")
    op.drop_index("ix_expenses_number",table_name="expenses")
    op.drop_table("expenses")
    op.drop_index("ix_employee_schedules_employee_weekday",table_name="employee_schedules")
    op.drop_table("employee_schedules")
    op.drop_column("agent_rents","addition")
    op.drop_column("agent_rents","discount")
    op.drop_column("agent_rents","base_amount")
    for col in ["notes","work_days","weekly_hours","employment_type","gender","identity_image","identity_number"]:
        op.drop_column("employees",col)
