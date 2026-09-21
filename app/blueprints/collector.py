from datetime import datetime, timezone
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import desc, or_

from ..extensions import db
from ..models import Agent, Client, ClientAgent, GateTransaction, Shift, Vehicle, VehicleAgent, VehicleType
from ..permissions import permission_required
from ..services.accounting import D, create_posted_entry, get_system_account
from ..services.accounts import ensure_agent_account, ensure_client_account, ensure_user_collector_account
from ..services.audit import audit

bp=Blueprint("collector",__name__,url_prefix="/collector")

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

def open_shift():
    shift=current_shift()
    if shift:
        return shift
    shift=Shift(collector_id=current_user.id,shift_name="وردية تشغيل",
        opened_at=datetime.now(timezone.utc),opening_balance=D("0"))
    db.session.add(shift)
    db.session.flush()
    return shift

@bp.route("",methods=["GET","POST"])
@permission_required("collector.post")
def index():
    if request.method=="POST":
        plate_number=request.form.get("plate_number","").strip()
        separator=request.form.get("plate_separator","").strip() or None
        client_name=request.form.get("client_name","").strip()
        direction=request.form.get("direction","entry")
        agent_id=request.form.get("agent_id") or None
        type_id=request.form.get("vehicle_type_id")
        amount=D(request.form.get("amount","0"))
        if not plate_number or not type_id:
            flash("رقم اللوحة ونوع المركبة مطلوبان","warning")
            return redirect(url_for("collector.index"))
        try:
            if direction not in {"entry","exit"}:
                raise ValueError("نوع الحركة غير صالح")
            if direction=="entry" and amount<=0:
                raise ValueError("مبلغ الدخول يجب أن يكون أكبر من صفر")
            if direction=="exit":
                amount=D("0")

            vehicle=Vehicle.query.filter_by(plate_number=plate_number,plate_separator=separator).first()
            if not vehicle:
                vehicle=Vehicle(plate_number=plate_number,plate_separator=separator,
                    vehicle_type_id=int(type_id),active=True)
                db.session.add(vehicle)
                db.session.flush()
            elif not vehicle.active:
                raise ValueError("المركبة موقوفة ولا يمكن تسجيل حركة عليها")

            if client_name and not vehicle.client_id:
                client=Client(code=f"C-{Client.query.count()+1:05d}",name=client_name,active=True)
                db.session.add(client)
                db.session.flush()
                ensure_client_account(client)
                vehicle.client_id=client.id

            agent=db.session.get(Agent,int(agent_id)) if agent_id else None
            if agent and not agent.active:
                raise ValueError("الوكيل المحدد موقوف")
            if agent:
                debit_account=ensure_agent_account(agent)
            else:
                debit_account=ensure_user_collector_account(current_user)

            shift=open_shift()
            entry=None
            now=datetime.now(timezone.utc)
            if direction=="entry":
                revenue=get_system_account("entry_revenue")
                entry=create_posted_entry(
                    description=f"إيراد دخول المركبة {plate_number}",
                    entry_date=now.date(),created_by_id=current_user.id,
                    source_type="gate",source_id=None,
                    lines=[{"account":debit_account,"debit":amount},
                           {"account":revenue,"credit":amount}],
                    prefix="GATE")
            tx=GateTransaction(
                receipt_number=f"GP-{now.strftime('%Y%m%d%H%M%S%f')}",
                transaction_date=now,direction=direction,vehicle_id=vehicle.id,
                client_id=vehicle.client_id,agent_id=agent.id if agent else None,
                collector_id=current_user.id,shift_id=shift.id,amount=amount,
                payment_method="cash",journal_entry_id=entry.id if entry else None,
                counted_for_work=(direction=="entry" and amount>0))
            db.session.add(tx)
            db.session.flush()
            if entry:
                entry.source_id=tx.id
            if agent:
                link=VehicleAgent.query.filter_by(vehicle_id=vehicle.id,agent_id=agent.id).first()
                if not link:
                    link=VehicleAgent(vehicle_id=vehicle.id,agent_id=agent.id,active=True)
                    db.session.add(link)
                link.last_used_at=now
            audit("gate_entry" if direction=="entry" else "gate_exit","gate_transaction",tx.id,
                  f"{tx.receipt_number} | لوحة={plate_number} | وكيل={agent.name if agent else 'عهدة المتحصل'} | مبلغ={amount}")
            db.session.commit()
            flash(f"تم التسجيل — {tx.receipt_number}","success")
            return redirect(url_for("collector.index"))
        except Exception as exc:
            db.session.rollback()
            flash(f"تعذر تسجيل العملية: {exc}","danger")

    recent=(GateTransaction.query.filter_by(collector_id=current_user.id)
        .order_by(GateTransaction.transaction_date.desc()).limit(15).all())
    return render_template("collector/index.html",
        vehicle_types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all(),
        agents=Agent.query.filter_by(active=True).order_by(Agent.name).all(),
        recent=recent,current_shift=current_shift())

@bp.get("/search")
@permission_required("collector.view")
def search():
    q=request.args.get("q","").strip()
    if not q:
        return jsonify([])
    rows=(Vehicle.query.filter(Vehicle.active.is_(True),
        or_(Vehicle.plate_number.ilike(f"%{q}%"),Vehicle.plate_separator.ilike(f"%{q}%")))
        .order_by(Vehicle.updated_at.desc()).limit(15).all())
    return jsonify([{
        "id":v.id,
        "plate":f"{v.plate_number}{(' / '+v.plate_separator) if v.plate_separator else ''}",
        "client_id":v.client_id,
        "client":v.client.name if v.client else None,
        "vehicle_type_id":v.vehicle_type_id,
        "vehicle_type":v.vehicle_type.name if v.vehicle_type else None,
        "suggested_agents":[{"id":a.id,"name":a.name} for a in recent_suggestions(v)]
    } for v in rows])
