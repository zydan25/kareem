"""Add fiscal years and retained earnings for closing entries.

Revision ID: 0010_fiscal_years_and_retained_earnings
Revises: 0009_audit_log_context
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_fiscal_years_and_retained_earnings"
down_revision = "0009_audit_log_context"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    root = conn.execute(sa.text(
        "SELECT id FROM accounts WHERE system_key='root_equity' ORDER BY id LIMIT 1"
    )).fetchone()
    if root:
        root_id = root[0]
    else:
        existing = conn.execute(sa.text(
            "SELECT id FROM accounts WHERE code='3' ORDER BY id LIMIT 1"
        )).fetchone()
        if existing:
            root_id = existing[0]
            conn.execute(sa.text(
                "UPDATE accounts SET system_key='root_equity', account_type='equity', "
                "is_group=TRUE, allow_manual_posting=FALSE WHERE id=:id"
            ), {"id": root_id})
        else:
            conn.execute(sa.text(
                "INSERT INTO accounts (code,name,account_type,parent_id,is_group,active,allow_manual_posting,system_key,created_at,updated_at) "
                "VALUES ('3','حقوق الملكية','equity',NULL,TRUE,TRUE,FALSE,'root_equity',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ))
            root_id = conn.execute(sa.text(
                "SELECT id FROM accounts WHERE system_key='root_equity' ORDER BY id LIMIT 1"
            )).scalar_one()

    if not conn.execute(sa.text(
        "SELECT id FROM accounts WHERE system_key='retained_earnings' ORDER BY id LIMIT 1"
    )).fetchone():
        candidate = "39902"
        suffix = 1
        while conn.execute(sa.text("SELECT id FROM accounts WHERE code=:code"), {"code": candidate}).fetchone():
            suffix += 1
            candidate = f"39902{suffix:02d}"
        conn.execute(sa.text(
            "INSERT INTO accounts (code,name,account_type,parent_id,is_group,active,allow_manual_posting,system_key,created_at,updated_at) "
            "VALUES (:code,'الأرباح المبقاة','equity',:parent_id,FALSE,TRUE,TRUE,'retained_earnings',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        ), {"code": candidate, "parent_id": root_id})

    op.create_table(
        "fiscal_years",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("closed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closing_journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("end_date >= start_date", name="ck_fiscal_year_dates"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_fiscal_year_status"),
    )
    op.create_index("ix_fiscal_years_start_date", "fiscal_years", ["start_date"])
    op.create_index("ix_fiscal_years_end_date", "fiscal_years", ["end_date"])
    op.create_index("ix_fiscal_years_status", "fiscal_years", ["status"])
    op.create_index("ix_fiscal_year_status_dates", "fiscal_years", ["status", "start_date", "end_date"])


def downgrade():
    op.drop_index("ix_fiscal_year_status_dates", table_name="fiscal_years")
    op.drop_index("ix_fiscal_years_status", table_name="fiscal_years")
    op.drop_index("ix_fiscal_years_end_date", table_name="fiscal_years")
    op.drop_index("ix_fiscal_years_start_date", table_name="fiscal_years")
    op.drop_table("fiscal_years")
    # Keep retained earnings: deleting an account referenced by posted journals is unsafe.
