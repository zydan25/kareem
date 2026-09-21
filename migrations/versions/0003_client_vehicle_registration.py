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
    op.alter_column(
        "vehicles",
        "plate_number",
        existing_type=sa.String(length=40),
        nullable=True,
    )
    op.add_column(
        "vehicles",
        sa.Column(
            "registration_status",
            sa.String(length=30),
            nullable=False,
            server_default="registered",
        ),
    )
    op.create_check_constraint(
        "ck_vehicle_registration_status",
        "vehicles",
        "registration_status IN ('registered','without_customs')",
    )
    op.execute("UPDATE vehicles SET registration_status='registered' WHERE registration_status IS NULL")
    op.alter_column("vehicles", "registration_status", server_default=None)


def downgrade():
    op.drop_constraint("ck_vehicle_registration_status", "vehicles", type_="check")
    op.drop_column("vehicles", "registration_status")
    op.alter_column(
        "vehicles",
        "plate_number",
        existing_type=sa.String(length=40),
        nullable=False,
    )
