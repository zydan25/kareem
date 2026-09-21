"""add employee fines

Revision ID: 0005_employee_fines
Revises: 0004_party_identities
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_employee_fines"
down_revision = "0004_party_identities"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employee_fines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("fine_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_employee_fines_employee_id", "employee_fines", ["employee_id"])
    op.create_index("ix_employee_fines_fine_date", "employee_fines", ["fine_date"])


def downgrade():
    op.drop_index("ix_employee_fines_fine_date", table_name="employee_fines")
    op.drop_index("ix_employee_fines_employee_id", table_name="employee_fines")
    op.drop_table("employee_fines")
