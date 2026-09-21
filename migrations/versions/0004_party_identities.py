"""Add optional identity document fields to agents and clients.

Revision ID: 0004_party_identities
Revises: 0003_client_vehicle_registration
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_party_identities"
down_revision = "0003_client_vehicle_registration"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("identity_type", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("identity_number", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("identity_image", sa.String(length=255), nullable=True))

    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("identity_type", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("identity_number", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("identity_image", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("identity_image")
        batch.drop_column("identity_number")
        batch.drop_column("identity_type")

    with op.batch_alter_table("agents") as batch:
        batch.drop_column("identity_image")
        batch.drop_column("identity_number")
        batch.drop_column("identity_type")
