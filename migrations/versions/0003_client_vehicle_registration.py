"""Add client vehicle registration status and allow unnumbered vehicles.

Revision ID: 0003_client_vehicle_registration
Revises: 0002_hr_expenses
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_client_vehicle_registration"
down_revision = "0002_hr_expenses"
branch_labels = None
depends_on = None


def upgrade():
    # Batch mode keeps the migration compatible with SQLite used by the test suite
    # and PostgreSQL used in production.
    with op.batch_alter_table("vehicles") as batch:
        batch.alter_column(
            "plate_number",
            existing_type=sa.String(length=40),
            nullable=True,
        )
        batch.add_column(
            sa.Column(
                "registration_status",
                sa.String(length=30),
                nullable=False,
                server_default="registered",
            )
        )
    op.execute("UPDATE vehicles SET registration_status='registered' WHERE registration_status IS NULL")
    with op.batch_alter_table("vehicles") as batch:
        batch.alter_column("registration_status", server_default=None)
        batch.create_check_constraint(
            "ck_vehicle_registration_status",
            "registration_status IN ('registered','without_customs')",
        )


def downgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_constraint("ck_vehicle_registration_status", type_="check")
        batch.drop_column("registration_status")
        batch.alter_column(
            "plate_number",
            existing_type=sa.String(length=40),
            nullable=False,
        )
