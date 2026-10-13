"""transaction-safe journal number allocation

Revision ID: 0008_journal_number_counter
Revises: 0007_default_client_vehicle
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_journal_number_counter"
down_revision = "0007_default_client_vehicle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "journal_number_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name="ck_journal_number_counters_singleton"),
        sa.CheckConstraint("last_value >= 0", name="ck_journal_number_counters_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Preserve the existing number series and never restart below an already
    # used suffix (including databases from which old entries were deleted).
    conn = op.get_bind()
    existing = conn.execute(sa.text("SELECT number FROM journal_entries")).fetchall()
    maximum_suffix = 0
    for (number,) in existing:
        try:
            suffix = int(str(number).rsplit("-", 1)[-1])
        except (TypeError, ValueError):
            continue
        maximum_suffix = max(maximum_suffix, suffix)

    initial_value = max(len(existing), maximum_suffix)
    conn.execute(
        sa.text(
            "INSERT INTO journal_number_counters (id, last_value) "
            "VALUES (1, :last_value)"
        ),
        {"last_value": initial_value},
    )


def downgrade():
    op.drop_table("journal_number_counters")
