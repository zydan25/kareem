"""default client vehicles and client-scoped plate uniqueness

Revision ID: 0007_default_client_vehicle
Revises: 0006_employee_cashboxes
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_default_client_vehicle"
down_revision = "0006_employee_cashboxes"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("vehicles", recreate="always") as batch:
            batch.add_column(sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
            batch.drop_constraint("uq_vehicle_plate", type_="unique")
            batch.create_unique_constraint(
                "uq_vehicle_client_plate",
                ["client_id", "plate_number", "plate_separator"],
            )
        conn.execute(sa.text('UPDATE vehicles SET is_default = 0 WHERE is_default IS NULL'))
    else:
        op.add_column("vehicles", sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
        try:
            op.drop_constraint("uq_vehicle_plate", "vehicles", type_="unique")
        except Exception:
            pass
        op.create_unique_constraint(
            "uq_vehicle_client_plate",
            "vehicles",
            ["client_id", "plate_number", "plate_separator"],
        )
        op.alter_column("vehicles", "is_default", server_default=None)

    row = conn.execute(
        sa.text("SELECT id FROM vehicle_types WHERE lower(name)=lower(:name) ORDER BY id LIMIT 1"),
        {"name": "افتراضي"},
    ).fetchone()
    if row:
        default_type_id = row[0]
        conn.execute(
            sa.text("UPDATE vehicle_types SET active = TRUE, is_system = TRUE WHERE id = :id"),
            {"id": default_type_id},
        )
    else:
        result = conn.execute(
            sa.text(
                "INSERT INTO vehicle_types (name, active, is_system, created_at, updated_at) "
                "VALUES (:name, TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"name": "افتراضي"},
        )
        default_type_id = conn.execute(
            sa.text("SELECT id FROM vehicle_types WHERE lower(name)=lower(:name) ORDER BY id LIMIT 1"),
            {"name": "افتراضي"},
        ).scalar()

    clients = conn.execute(sa.text("SELECT id FROM clients ORDER BY id")).fetchall()
    for (client_id,) in clients:
        exists = conn.execute(
            sa.text("SELECT id FROM vehicles WHERE client_id=:client_id LIMIT 1"),
            {"client_id": client_id},
        ).fetchone()
        if exists:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO vehicles "
                "(plate_number, plate_separator, plate_letters, registration_status, vehicle_type_id, "
                "client_id, notes, active, is_default, created_at, updated_at) "
                "VALUES ('0', '0', NULL, 'registered', :type_id, :client_id, "
                "'مركبة افتراضية — تُستخدم عند عدم تسجيل مركبة فعلية', TRUE, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"type_id": default_type_id, "client_id": client_id},
        )


def downgrade():
    conn = op.get_bind()
    try:
        op.drop_constraint("uq_vehicle_client_plate", "vehicles", type_="unique")
    except Exception:
        pass
    try:
        op.create_unique_constraint("uq_vehicle_plate", "vehicles", ["plate_number", "plate_separator"])
    except Exception:
        pass
    try:
        op.drop_column("vehicles", "is_default")
    except Exception:
        pass
