from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import desc, func, or_

from ..extensions import db
from ..models import Agent, Client, ClientAgent, GateTransaction, Shift, Vehicle, VehicleAgent, VehicleType
from ..permissions import permission_required
from ..services.accounting import D, account_balance, create_posted_entry, get_system_account
from ..services.accounts import ensure_agent_account, ensure_client_account, ensure_user_collector_account
from ..services.audit import audit
from ..services.operations import ensure_user_shift
from ..services.vehicles import default_vehicle_type, ensure_default_vehicle

bp=Blueprint("collector",__name__,url_prefix="/collector")
LOCAL_TZ=ZoneInfo("Asia/Aden")
UTC_TZ=ZoneInfo("UTC")

def recent_suggestions(vehicle):
    rows=(db.session.query(Agent)
        .join(VehicleAgent,VehicleAgent.agent_id==Agent.id)
        .filter(VehicleAgent.vehicle_id==vehicle.id,VehicleAgent.active.is_(True),Agent.active.is_(True))
        .order_by(desc(VehicleAgent.last_used_at).nullslast()).limit(8).all())
    if vehicle.client_id and len(rows)<8:
        existing={a.id for a in rows}
        client_rows=(db.session.query(Agent)
            .join(ClientAgent,ClientAgent.agent_id==Agent.id)
            .filter(ClientAgent.client_id==vehicle.client_id,ClientAgent.active.is_(True),Agent.active.is_(True))
            .order_by(ClientAgent.priority.asc()).limit(8).all())
        rows.extend([a for a in client_rows if a.id not in existing][:8-len(rows)])
    return rows

def current_shift():
    return (Shift.query.filter_by(collector_id=current_user.id,status="open")
        .order_by(desc(Shift.opened_at)).first())

@bp.route("",methods=["GET","POST"])
@permission_required("collector.post")
def index():
    if request.method=="POST":
        plate_number=request.form.get("plate_number","").strip() or None
        separator=request.form.get("plate_separator","").strip() or None
        vehicle_id=request.form.get("vehicle_id",type=int)
        registration_status=request.form.get("registration_status","registered").strip() or "registered"
        client_id=request.form.get("client_id",type=int)
        client_name=request.form.get("client_name","").strip()
        client_phone=request.form.get("client_phone","").strip()
        client_address=request.form.get("client_address","").strip()
        client_notes=request.form.get("client_notes","").strip()
        gate_notes=request.form.get("gate_notes","").strip()
        direction=request.form.get("direction","entry")
        agent_id=request.form.get("agent_id",type=int)
        type_id=request.form.get("vehicle_type_id",type=int)
        amount=D(request.form.get("amount","0"))

        try:
            if direction not in {"entry","exit"}:
                raise ValueError("نوع الحركة غير صالح")
            if registration_status not in {"registered","without_customs"}:
                raise ValueError("حالة المركبة غير صالحة")
            if amount<=0:
                raise ValueError("المبلغ يجب أن يكون أكبر من صفر في الدخول والخروج")

            client=None
            if client_id:
                client=db.session.get(Client,client_id)
                if not client or not client.active:
                    raise ValueError("العميل المحدد غير صالح")
            elif client_name:
                client=Client.query.filter(Client.name.ilike(client_name)).first()
                if not client:
                    client=Client(code=f"C-{Client.query.count()+1:05d}",name=client_name,phone=client_phone or None,
                        address=client_address or None,notes=client_notes or None,active=True)
                    db.session.add(client)
                    db.session.flush()
                    ensure_client_account(client)

            vehicle=db.session.get(Vehicle,vehicle_id) if vehicle_id else None
            if vehicle and not vehicle.active:
                raise ValueError("المركبة موقوفة ولا يمكن تسجيل حركة عليها")

            if not vehicle and plate_number:
                vehicle_query=Vehicle.query.filter_by(plate_number=plate_number,plate_separator=separator)
                if client:
                    vehicle_query=vehicle_query.filter(Vehicle.client_id==client.id)
                vehicle=vehicle_query.first()
                if vehicle and not vehicle.active:
                    raise ValueError("المركبة موقوفة ولا يمكن تسجيل حركة عليها")

            is_default_request=request.form.get("is_default_vehicle")=="1"
            if not vehicle:
                if client and is_default_request:
                    vehicle=ensure_default_vehicle(client)
                elif client and not plate_number and not type_id:
                    vehicle=ensure_default_vehicle(client)
                else:
                    if registration_status=="registered" and not plate_number:
                        raise ValueError("أدخل رقم اللوحة أو اختر «بدون جمارك»")
                    if not type_id:
                        raise ValueError("اختر نوع المركبة عند إضافة مركبة جديدة")
                    vehicle=Vehicle(plate_number=plate_number,plate_separator=separator,
                        vehicle_type_id=type_id,registration_status=registration_status,active=True,
                        client_id=client.id if client else None,is_default=False)
                    db.session.add(vehicle)
                    db.session.flush()

            if client:
                if vehicle.client_id and vehicle.client_id != client.id:
                    raise ValueError("المركبة المحددة مرتبطة بعميل آخر")
                vehicle.client_id=client.id

            agent=db.session.get(Agent,agent_id) if agent_id else None
            if agent and not agent.active:
                raise ValueError("الوكيل المحدد موقوف")

            shift=ensure_user_shift(current_user.id,"وردية البوابة")
            custody=ensure_user_collector_account(current_user)
            revenue=get_system_account("entry_revenue" if direction=="entry" else "exit_revenue")
            # Entry fees assigned to an agent are receivables on that agent's
            # account; only unassigned gate cash becomes the collector's cashbox.
            debit_account=ensure_agent_account(agent) if direction=="entry" and agent else custody
            now=datetime.now(timezone.utc)
            entry=create_posted_entry(
                description=f"{'إيراد دخول' if direction=='entry' else 'إيراد خروج'} المركبة {plate_number}",
                entry_date=now.date(),created_by_id=current_user.id,source_type="gate",source_id=None,
                lines=[{"account":debit_account,"debit":amount},{"account":revenue,"credit":amount}],
                prefix="GIN" if direction=="entry" else "GOUT")
            tx=GateTransaction(
                receipt_number=f"GP-{now.strftime('%Y%m%d%H%M%S%f')}",
                transaction_date=now,direction=direction,vehicle_id=vehicle.id,
                client_id=client.id if client else vehicle.client_id,agent_id=agent.id if agent else None,
                collector_id=current_user.id,shift_id=shift.id,amount=amount,payment_method="cash",
                notes=gate_notes or None,journal_entry_id=entry.id,counted_for_work=True)
            db.session.add(tx)
            db.session.flush()
            entry.source_id=tx.id
            if agent:
                link=VehicleAgent.query.filter_by(vehicle_id=vehicle.id,agent_id=agent.id).first()
                if not link:
                    link=VehicleAgent(vehicle_id=vehicle.id,agent_id=agent.id,active=True)
                    db.session.add(link)
                link.last_used_at=now

            audit("gate_entry" if direction=="entry" else "gate_exit","gate_transaction",tx.id,
                  f"{tx.receipt_number} | لوحة={plate_number} | عميل={client.name if client else '—'} | وكيل={agent.name if agent else '—'} | مبلغ={amount}")
            db.session.commit()
            flash(f"تم تسجيل {'الدخول' if direction=='entry' else 'الخروج'} — {tx.receipt_number}","success")
            return redirect(url_for("collector.index"))
        except Exception as exc:
            db.session.rollback()
            flash(f"تعذر تسجيل العملية: {exc}","danger")

    today=datetime.now(LOCAL_TZ).date()
    local_start=datetime.combine(today,datetime.min.time(),tzinfo=LOCAL_TZ).astimezone(UTC_TZ)
    local_end=(datetime.combine(today,datetime.min.time(),tzinfo=LOCAL_TZ)+timedelta(days=1)).astimezone(UTC_TZ)
    day_rows=(GateTransaction.query.filter(GateTransaction.collector_id==current_user.id,
        GateTransaction.transaction_date>=local_start,GateTransaction.transaction_date<local_end)
        .order_by(GateTransaction.transaction_date.desc()).all())
    counted_rows=[x for x in day_rows if x.counted_for_work]
    daily_total=sum((D(x.amount) for x in counted_rows),D(0))
    daily_count=len(counted_rows)
    daily_entries=len([x for x in counted_rows if x.direction=="entry"])
    daily_exits=len([x for x in counted_rows if x.direction=="exit"])
    employee=current_user.employee
    custody_balance=account_balance(employee.account_id) if employee and employee.account_id else D(0)

    return render_template("collector/index.html",
        vehicle_types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all(),
        agents=Agent.query.filter_by(active=True).order_by(Agent.name).all(),
        recent=day_rows[:20],current_shift=current_shift(),
        daily_total=daily_total,daily_count=daily_count,daily_entries=daily_entries,
        daily_exits=daily_exits,custody_balance=custody_balance,today=today)

@bp.get("/transactions/<int:transaction_id>")
@permission_required("collector.view")
def transaction_detail(transaction_id):
    tx=db.session.get(GateTransaction,transaction_id)
    if not tx: return ("الحركة غير موجودة",404)
    if tx.collector_id != current_user.id and current_user.role=="collector":
        return ("Forbidden",403)
    return render_template("collector/transaction_detail.html",tx=tx)

@bp.get("/search")
@permission_required("collector.view")
def search():
    q=request.args.get("q","").strip()
    if not q:
        return jsonify([])
    rows=(Vehicle.query.filter(Vehicle.active.is_(True),
        or_(Vehicle.plate_number.ilike(f"%{q}%"),Vehicle.plate_separator.ilike(f"%{q}%"),Vehicle.plate_letters.ilike(f"%{q}%")))
        .order_by(Vehicle.updated_at.desc()).limit(15).all())
    return jsonify([{
        "id":v.id,
        "plate":f"{v.plate_number}{(' / '+v.plate_separator) if v.plate_separator else ''}",
        "client_id":v.client_id,
        "client":v.client.name if v.client else None,
        "client_phone":v.client.phone if v.client else None,
        "client_address":v.client.address if v.client else None,
        "vehicle_type_id":v.vehicle_type_id,
        "vehicle_type":v.vehicle_type.name if v.vehicle_type else None,
        "suggested_agents":[{"id":a.id,"name":a.name} for a in recent_suggestions(v)]
    } for v in rows])

@bp.get("/search-clients")
@permission_required("collector.view")
def search_clients():
    q=request.args.get("q","").strip()
    if not q:
        return jsonify([])

    compact=q.replace(" ","").replace("-","").replace("/","")
    phone_compact=q.replace(" ","").replace("-","").replace("(","").replace(")","")
    results=[]

    client_rows=(Client.query
        .filter(Client.active.is_(True),
            or_(
                Client.name.ilike(f"%{q}%"),
                Client.phone.ilike(f"%{q}%"),
                func.replace(func.replace(func.replace(Client.phone," ",""),"-",""),"+","").ilike(f"%{phone_compact}%"),
            ))
        .order_by(Client.name)
        .limit(10).all())

    default_type=default_vehicle_type(db.session)
    for client in client_rows:
        vehicles=(Vehicle.query
            .filter(Vehicle.client_id==client.id,Vehicle.active.is_(True))
            .order_by(Vehicle.is_default.desc(),Vehicle.id).all())
        vehicle_payload=[{
                "id":v.id,
                "plate":v.plate_number,
                "separator":v.plate_separator,
                "letters":v.plate_letters,
                "registration_status":v.registration_status,
                "vehicle_type_id":v.vehicle_type_id,
                "vehicle_type":v.vehicle_type.name if v.vehicle_type else None,
                "notes":v.notes,
                "is_default":bool(v.is_default),
            } for v in vehicles]
        if not vehicle_payload:
            vehicle_payload=[{
                "id":None,
                "plate":"0",
                "separator":"0",
                "letters":None,
                "registration_status":"registered",
                "vehicle_type_id":default_type.id,
                "vehicle_type":default_type.name,
                "notes":"مركبة افتراضية",
                "is_default":True,
            }]
        results.append({
            "kind":"client",
            "id":client.id,
            "name":client.name,
            "phone":client.phone,
            "address":client.address,
            "vehicles":vehicle_payload,
        })

    # A plate may be typed without spaces/slashes/dashes; compare against a
    # compacted database value as well.
    vehicle_rows=(Vehicle.query
        .filter(Vehicle.active.is_(True),
            or_(
                Vehicle.plate_number.ilike(f"%{q}%"),
                Vehicle.plate_separator.ilike(f"%{q}%"),
                Vehicle.plate_letters.ilike(f"%{q}%"),
                func.replace(func.replace(func.replace(Vehicle.plate_number," ",""),"-",""),"/","").ilike(f"%{compact}%"),
            ))
        .order_by(Vehicle.updated_at.desc()).limit(10).all())

    for vehicle in vehicle_rows:
        client=vehicle.client
        results.append({
            "kind":"vehicle",
            "id":client.id if client else None,
            "name":client.name if client else "مركبة بدون عميل",
            "phone":client.phone if client else None,
            "address":client.address if client else None,
            "plate":vehicle.plate_number,
            "vehicle_id":vehicle.id,
            "vehicle_type_id":vehicle.vehicle_type_id,
            "vehicle_type":vehicle.vehicle_type.name if vehicle.vehicle_type else None,
            "vehicle_separator":vehicle.plate_separator,
            "vehicle_letters":vehicle.plate_letters,
            "registration_status":vehicle.registration_status,
        })

    vehicle_client_ids={x["id"] for x in results if x["kind"]=="vehicle" and x.get("id")}
    final=[]
    for item in results:
        if item["kind"]=="client" and item["id"] in vehicle_client_ids:
            # Keep the vehicle-search result more specific, but retain the
            # customer's vehicle list when the UI explicitly searched a plate.
            continue
        final.append(item)
    return jsonify(final[:15])
