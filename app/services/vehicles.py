from ..extensions import db
from ..models import Vehicle, VehicleType

DEFAULT_PLATE = "0"
DEFAULT_SEPARATOR = "0"
DEFAULT_TYPE_NAME = "افتراضي"

def default_vehicle_type(session=None):
    session = session or db.session
    row = session.query(VehicleType).filter_by(name=DEFAULT_TYPE_NAME).first()
    if row:
        row.active = True
        return row
    row = VehicleType(name=DEFAULT_TYPE_NAME, active=True, is_system=True)
    session.add(row)
    session.flush()
    return row

def ensure_default_vehicle(client, session=None):
    session = session or db.session
    if not client:
        raise ValueError("العميل مطلوب للمركبة الافتراضية")

    vehicle_type = default_vehicle_type(session)
    existing = (session.query(Vehicle)
        .filter_by(client_id=client.id, is_default=True)
        .order_by(Vehicle.id.desc())
        .first())
    if existing:
        existing.active = True
        existing.plate_number = DEFAULT_PLATE
        existing.plate_separator = DEFAULT_SEPARATOR
        existing.vehicle_type_id = vehicle_type.id
        existing.registration_status = "registered"
        existing.is_default = True
        return existing

    vehicle = Vehicle(
        plate_number=DEFAULT_PLATE,
        plate_separator=DEFAULT_SEPARATOR,
        plate_letters=None,
        registration_status="registered",
        vehicle_type_id=vehicle_type.id,
        client_id=client.id,
        notes="مركبة افتراضية — تُستخدم عند عدم تسجيل مركبة فعلية",
        active=True,
        is_default=True,
    )
    session.add(vehicle)
    session.flush()
    return vehicle
