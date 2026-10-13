"""Store actor and request context with each audit event.

Revision ID: 0009_audit_log_context
Revises: 0008_journal_number_counter
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_audit_log_context"
down_revision = "0008_journal_number_counter"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_logs", sa.Column("actor_username", sa.String(length=80), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_name", sa.String(length=160), nullable=True))
    op.add_column("audit_logs", sa.Column("request_method", sa.String(length=12), nullable=True))
    op.add_column("audit_logs", sa.Column("request_path", sa.String(length=255), nullable=True))
    op.add_column("audit_logs", sa.Column("user_agent", sa.String(length=255), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE audit_logs SET "
        "actor_username = (SELECT username FROM users WHERE users.id = audit_logs.user_id), "
        "actor_name = (SELECT full_name FROM users WHERE users.id = audit_logs.user_id) "
        "WHERE user_id IS NOT NULL"
    ))

    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_actor_username", "audit_logs", ["actor_username"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])
    op.create_index("ix_audit_logs_entity_created", "audit_logs", ["entity_type", "created_at"])


def downgrade():
    op.drop_index("ix_audit_logs_entity_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_username", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_column("audit_logs", "user_agent")
    op.drop_column("audit_logs", "request_path")
    op.drop_column("audit_logs", "request_method")
    op.drop_column("audit_logs", "actor_name")
    op.drop_column("audit_logs", "actor_username")
