from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user
from sqlalchemy import or_, desc
from ..extensions import db
from ..models import Vehicle, VehicleType, Client, Agent, ClientAgent, VehicleAgent, Shift, GateTransaction
from ..services.accounting import create_posted_entry, get_system_account
from ..services.accounts import ensure_child_account
from ..permissions import permission_required

bp=Blueprint("collector",__name__,url_prefix="/collector")

def recent_suggestions(vehicle):
    rows=(db.session.query(Agent).join(VehicleAgent,VehicleAgent.agent_id==Agent.id)
        .filter(VehicleAgent.vehicle_id==vehicle.id,VehicleAgent.active.is_(True),Agent.active.is_(True))
        .order_by(desc(VehicleAgent.last_used_at.nullslast())).limit(8).all())
    if vehicle.client_id and len(rows)<8:
        existing={a.id for a in rows}
        client_rows=(db.session.query(Agent).join(ClientAgent,ClientAgent.agent_id==Agent.id)
            .filter(ClientAgent.client_id==vehicle.client_id,ClientAgent.active.is_(True),Agent.active.is_(True))
            .order_by(ClientAgent.priority.asc()).limit(8).all())
        rows.extend([a for a in client_rows if a.id not in existing][:8-len(rows)])
    return rows

def open_shift():
    shift=(db.session.query(Shift).filter_by(collector_id=current_user.id,status="open")
        .order_by(desc(Shift.opened_at)).first())
    if not shift:
        shift=Shift(collector_id=current_user.id,shift_name="وردية تشغيل",opened_at=datetime.now(timezone.utc))
        db.session.add(shift); db.session.flush()
    return shift

@bp.route("",methods=["GET","POST"])
@permission_required("collector.post")
def index():
    if request.method=="POST":
        plate_number=request.form.get("plate_number","").strip()
        separator=request.form.get("plate_separator","").strip() or None
        client_name=request.form.get("client_name","").strip()
        amount=request.form.get("amount","0")
        direction=request.form.get("direction","entry")
        agent_id=request.form.get("agent_id") or None
        type_id=request.form.get("vehicle_type_id")
        if not plate_number or not type_id:
            flash("رقم اللوحة ونوع المركبة حقول مطلوبة","warning")
            return redirect(url_for("collector.index"))
        try:
            amount=float(amount or 0)
            if direction not in {"entry","exit"}: raise ValueError("نوع الحركة غير صالح")
            if direction=="exit": amount=0.0

            vehicle=db.session.query(Vehicle).filter_by(plate_number=plate_number,plate_separator=separator).first()
            if not vehicle:
                vehicle=Vehicle(plate_number=plate_number,plate_separator=separator,vehicle_type_id=int(type_id))
                if client_name:
                    client=Client(code=f"C-{db.session.query(Client).count()+1:05d}",name=client_name)
                    db.session.add(client); db.session.flush()
                    client.account_id=ensure_child_account(parent_key="clients_root",code=f"103{client.id:04d}",name=f"عميل: {client.name}").id
                    vehicle.client_id=client.id
                db.session.add(vehicle); db.session.flush()
            elif client_name and not vehicle.client_id:
                client=Client(code=f"C-{db.session.query(Client).count()+1:05d}",name=client_name)
                db.session.add(client); db.session.flush()
                client.account_id=ensure_child_account(parent_key="clients_root",code=f"103{client.id:04d}",name=f"عميل: {client.name}").id
                vehicle.client_id=client.id

            agent=db.session.get(Agent,int(agent_id)) if agent_id else None
            if agent:
                from ..models import Account
                if agent.account_id: debit_account=db.session.get(Account,agent.account_id)
                else:
                    debit_account=ensure_child_account(parent_key="agents_root",code=f"104{agent.id:04d}",name=f"وكيل: {agent.name}")
                    agent.account_id=debit_account.id
            else:
                from ..models import Employee,Account
                if current_user.employee_id:
                    emp=db.session.get(Employee,current_user.employee_id)
                    if emp and emp.account_id: debit_account=db.session.get(Account,emp.account_id)
                    else:
                        debit_account=ensure_child_account(parent_key="collector_root",code=f"102{current_user.id:04d}",name=f"عهدة: {current_user.full_name}")
                        if emp: emp.account_id=debit_account.id
                else:
                    debit_account=ensure_child_account(parent_key="collector_root",code=f"102U{current_user.id:04d}",name=f"عهدة: {current_user.full_name}")

            entry=None
            if direction=="entry":
                revenue=get_system_account("entry_revenue")
                entry=create_posted_entry(description=f"إيراد دخول المركبة {plate_number}",
                    entry_date=datetime.now(timezone.utc).date(),created_by_id=current_user.id,source_type="gate",
                    lines=[{"account":debit_account,"debit":amount},{"account":revenue,"credit":amount}],prefix="GATE")

            shift=open_shift(); now=datetime.now(timezone.utc)
            tx=GateTransaction(receipt_number=f"GP-{now.strftime('%Y%m%d%H%M%S%f')}",transaction_date=now,
                direction=direction,vehicle_id=vehicle.id,client_id=vehicle.client_id,agent_id=agent.id if agent else None,
                collector_id=current_user.id,shift_id=shift.id,amount=amount,journal_entry_id=entry.id if entry else None)
            db.session.add(tx); db.session.flush()
            if agent:
                link=db.session.query(VehicleAgent).filter_by(vehicle_id=vehicle.id,agent_id=agent.id).first()
                if not link: link=VehicleAgent(vehicle_id=vehicle.id,agent_id=agent.id); db.session.add(link)
                link.last_used_at=now
            db.session.commit()
            flash(f"تم تسجيل الحركة بنجاح — {('سند دخول' if direction=='entry' else 'سجل خروج')} {tx.receipt_number}","success")
            return redirect(url_for("collector.index"))
        except Exception as exc:
            db.session.rollback(); flash(f"تعذر تسجيل العملية: {exc}","danger")
    return render_template("collector/index.html",
        vehicle_types=db.session.query(VehicleType).filter_by(active=True).order_by(VehicleType.name).all(),
        agents=db.session.query(Agent).filter_by(active=True).order_by(Agent.name).all())

@bp.get("/search")
@permission_required("collector.view")
def search():
    q=request.args.get("q","").strip()
    rows=(db.session.query(Vehicle).filter(Vehicle.active.is_(True),
        or_(Vehicle.plate_number.ilike(f"%{q}%"),Vehicle.plate_separator.ilike(f"%{q}%")))
        .order_by(Vehicle.updated_at.desc()).limit(15).all())
    return jsonify([{"id":v.id,"plate":f"{v.plate_number}{(' / '+v.plate_separator) if v.plate_separator else ''}",
        "client_id":v.client_id,"client":v.client.name if v.client else None,
        "suggested_agents":[{"id":a.id,"name":a.name} for a in recent_suggestions(v)]} for v in rows])
