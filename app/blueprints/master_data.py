from datetime import date, time
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy import func, or_

from ..extensions import db
from ..models import Agent, AgentLease, AgentRent, AuditLog, Client, ClientAgent, Employee, EmployeeFine, EmployeeSchedule, GateTransaction, PayrollLine, Role, Shift, User, Vehicle, VehicleAgent, VehicleType
from ..permissions import can, permission_required
from ..services.accounting import account_balance, create_posted_entry, get_system_account
from ..services.audit import audit
from ..services.accounts import ensure_agent_account, ensure_client_account, ensure_employee_account, ensure_employee_payroll_account
from ..services.setup import ensure_employees_for_users

bp=Blueprint("master_data",__name__)

ROLE_LABELS={"admin":"مدير النظام","manager":"مدير","accountant":"محاسب","collector":"متحصل","auditor":"مراجع"}
WEEKDAYS=[(0,"السبت"),(1,"الأحد"),(2,"الاثنين"),(3,"الثلاثاء"),(4,"الأربعاء"),(5,"الخميس"),(6,"الجمعة")]

def next_code(prefix, model):
    return f"{prefix}-{db.session.query(model).count()+1:05d}"

def D(value):
    from decimal import Decimal
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))

def _save_identity_image(emp):
    image=request.files.get("identity_image")
    if not image or not image.filename:
        return
    original=Path(image.filename).name
    suffix=Path(original).suffix.lower()
    allowed={".jpg",".jpeg",".png",".webp"}
    if suffix not in allowed:
        raise ValueError("صورة البطاقة يجب أن تكون JPG أو PNG أو WEBP")
    folder=Path(current_app.config["UPLOAD_FOLDER"]) / "employee_ids"
    folder.mkdir(parents=True,exist_ok=True)
    filename=f"employee-{emp.id}{suffix}"
    image.save(folder/filename)
    emp.identity_image=f"employee_ids/{filename}"

def _save_party_identity(obj, prefix):
    image=request.files.get("identity_image")
    identity_type=request.form.get("identity_type") or None
    identity_number=request.form.get("identity_number") or None
    obj.identity_type=identity_type
    obj.identity_number=identity_number
    if not image or not image.filename:
        return
    suffix=Path(Path(image.filename).name).suffix.lower()
    if suffix not in {".jpg",".jpeg",".png",".webp"}:
        raise ValueError("صورة الهوية يجب أن تكون JPG أو PNG أو WEBP")
    folder=Path(current_app.config["UPLOAD_FOLDER"]) / "party_ids"
    folder.mkdir(parents=True,exist_ok=True)
    filename=f"{prefix}-{obj.id}{suffix}"
    image.save(folder/filename)
    obj.identity_image=f"party_ids/{filename}"

def _save_employee_login(emp):
    # Employee is the source of truth for login accounts. Username is always
    # the employee phone; there is no separate "add user" workflow.
    username=(emp.phone or "").strip()
    password=request.form.get("login_password","")
    role=request.form.get("login_role") or Role.COLLECTOR.value
    if not username:
        raise ValueError("رقم الهاتف مطلوب لإنشاء حساب الموظف تلقائيًا")
    if not emp.phone:
        raise ValueError("أدخل رقم هاتف الموظف قبل إنشاء حساب الدخول")
    if not password and not emp.user:
        raise ValueError("عند إنشاء حساب دخول للموظف يجب إدخال كلمة المرور")
    existing=User.query.filter(User.username==username).first()
    if existing and (not emp.user or existing.id!=emp.user.id):
        raise ValueError("اسم المستخدم مستخدم مسبقًا")
    other_phone=User.query.filter(User.phone==emp.phone,User.id!=(emp.user.id if emp.user else -1)).first()
    if other_phone:
        raise ValueError("رقم هاتف الموظف مرتبط بحساب مستخدم آخر")
    user=emp.user
    if user:
        user.username=username
        user.full_name=emp.full_name
        user.phone=emp.phone
        user.role=role
        user.active=emp.active
        if password:
            user.set_password(password)
        audit("update","user",user.id,user.username)
    else:
        user=User(username=username,full_name=emp.full_name,phone=emp.phone,role=role,active=emp.active,employee_id=emp.id)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        audit("create","user",user.id,user.username)
    return user

def _sync_work_days(emp):
    days=sorted({str(s.weekday) for s in emp.schedules if s.active})
    emp.work_days=",".join(days)

@bp.route("/agents",methods=["GET","POST"])
@permission_required("agents.view")
def agents():
    q=request.args.get("q","").strip()
    query=Agent.query
    if q: query=query.filter(or_(Agent.name.ilike(f"%{q}%"),Agent.code.ilike(f"%{q}%"),Agent.phone.ilike(f"%{q}%")))
    rows=query.order_by(Agent.active.desc(),Agent.name).all()
    if request.method=="POST":
        if not can("agents.manage"): return ("Forbidden",403)
        try:
            agent=Agent(code=next_code("AG",Agent),name=request.form["name"].strip(),
                phone=request.form.get("phone"),identity_type=request.form.get("identity_type") or None,
                identity_number=request.form.get("identity_number") or None,notes=request.form.get("notes"),active=True)
            db.session.add(agent); db.session.flush(); _save_party_identity(agent,"agent"); ensure_agent_account(agent)
            audit("create","agent",agent.id,agent.name); db.session.commit(); flash("تم إضافة الوكيل وإنشاء حسابه","success")
            return redirect(url_for("master_data.agents"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/agents.html",agents=rows,can_manage=can("agents.manage"),q=q)

@bp.get("/agents/<int:agent_id>")
@permission_required("agents.view")
def agent_detail(agent_id):
    agent=db.session.get(Agent,agent_id)
    if not agent: return ("غير موجود",404)
    balance=account_balance(agent.account_id) if agent.account_id else D(0)
    vehicles=(db.session.query(Vehicle).join(VehicleAgent,VehicleAgent.vehicle_id==Vehicle.id)
              .filter(VehicleAgent.agent_id==agent.id,VehicleAgent.active.is_(True)).order_by(Vehicle.plate_number).all())
    leases=AgentLease.query.filter_by(agent_id=agent.id).order_by(AgentLease.active.desc(),AgentLease.id.desc()).all()
    rents=AgentRent.query.filter_by(agent_id=agent.id).order_by(AgentRent.rent_month.desc()).limit(24).all()
    return render_template("master_data/agent_detail.html",agent=agent,balance=balance,vehicles=vehicles,leases=leases,rents=rents)

@bp.route("/agents/<int:agent_id>/edit",methods=["GET","POST"])
@permission_required("agents.manage")
def edit_agent(agent_id):
    agent=db.session.get(Agent,agent_id)
    if not agent: return ("غير موجود",404)
    if request.method=="POST":
        try:
            agent.name=request.form["name"].strip()
            agent.phone=request.form.get("phone"); agent.identity_type=request.form.get("identity_type") or None
            agent.identity_number=request.form.get("identity_number") or None; agent.notes=request.form.get("notes")
            _save_party_identity(agent,"agent"); ensure_agent_account(agent); audit("update","agent",agent.id,agent.name); db.session.commit()
            flash("تم تحديث الوكيل","success"); return redirect(url_for("master_data.agent_detail",agent_id=agent.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/agent_form.html",agent=agent)

@bp.post("/agents/<int:agent_id>/delete")
@permission_required("agents.manage")
def delete_agent(agent_id):
    agent=db.session.get(Agent,agent_id)
    if not agent: return ("غير موجود",404)
    agent.active=False
    audit("deactivate","agent",agent.id,agent.name); db.session.commit()
    flash("تم إيقاف الوكيل مع حفظ سجله المالي","success")
    return redirect(url_for("master_data.agents"))

@bp.route("/agents/<int:agent_id>/toggle",methods=["POST"])
@permission_required("agents.manage")
def toggle_agent(agent_id):
    return delete_agent(agent_id) if db.session.get(Agent,agent_id) and db.session.get(Agent,agent_id).active else _toggle_agent_on(agent_id)

def _toggle_agent_on(agent_id):
    agent=db.session.get(Agent,agent_id)
    if not agent: return ("غير موجود",404)
    agent.active=True; audit("activate","agent",agent.id,agent.name); db.session.commit(); return redirect(url_for("master_data.agents"))

@bp.route("/clients",methods=["GET","POST"])
@permission_required("clients.view")
def clients():
    q=request.args.get("q","").strip()
    query=Client.query
    if q: query=query.filter(or_(Client.name.ilike(f"%{q}%"),Client.code.ilike(f"%{q}%"),Client.phone.ilike(f"%{q}%")))
    rows=query.order_by(Client.active.desc(),Client.name).all()
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    if request.method=="POST":
        if not can("clients.manage"): return ("Forbidden",403)
        try:
            client=Client(code=next_code("CL",Client),name=request.form["name"].strip(),
                phone=request.form.get("phone"),identity_type=request.form.get("identity_type") or None,
                identity_number=request.form.get("identity_number") or None,address=request.form.get("address"),notes=request.form.get("notes"),active=True)
            db.session.add(client); db.session.flush(); _save_party_identity(client,"client"); ensure_client_account(client)

            # Every newly created customer must have at least one vehicle.
            plates=request.form.getlist("vehicle_plate_number")
            statuses=request.form.getlist("vehicle_registration_status")
            type_ids=request.form.getlist("vehicle_type_id")
            vehicle_notes=request.form.getlist("vehicle_notes")
            vehicle_separators=request.form.getlist("vehicle_plate_separator")
            vehicle_letters=request.form.getlist("vehicle_plate_letters")
            created=0
            for i,type_id in enumerate(type_ids):
                plate=(plates[i] if i<len(plates) else "").strip() or None
                status=(statuses[i] if i<len(statuses) else "registered").strip() or "registered"
                note=(vehicle_notes[i] if i<len(vehicle_notes) else "").strip() or None
                if not type_id:
                    continue
                if status=="registered" and not plate:
                    raise ValueError("المركبة ذات اللوحة الجمركية يجب أن تحتوي على رقم لوحة")
                vehicle=Vehicle(
                    plate_number=plate,
                    plate_separator=(vehicle_separators[i] if i<len(vehicle_separators) else "").strip() or None,
                    plate_letters=(vehicle_letters[i] if i<len(vehicle_letters) else "").strip() or None,
                    registration_status=status,
                    vehicle_type_id=int(type_id),
                    client_id=client.id,
                    notes=note,
                    active=True,
                )
                db.session.add(vehicle); db.session.flush()
                created+=1

            if created<1:
                raise ValueError("يجب إضافة مركبة واحدة على الأقل للعميل")
            for aid in {int(x) for x in request.form.getlist("agent_ids")}:
                db.session.add(ClientAgent(client_id=client.id,agent_id=aid,priority=1))
            audit("create","client",client.id,client.name); db.session.commit(); flash(f"تم إضافة العميل وحسابه وتسجيل {created} مركبة","success")
            return redirect(url_for("master_data.client_detail",client_id=client.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    vehicle_types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all()
    return render_template("master_data/clients.html",clients=rows,agents=agents,vehicle_types=vehicle_types,can_manage=can("clients.manage"),q=q)

@bp.get("/clients/<int:client_id>")
@permission_required("clients.view")
def client_detail(client_id):
    client=db.session.get(Client,client_id)
    if not client: return ("غير موجود",404)
    balance=account_balance(client.account_id) if client.account_id else D(0)
    vehicles=Vehicle.query.filter_by(client_id=client.id).order_by(Vehicle.active.desc(),Vehicle.plate_number).all()
    agents=(db.session.query(Agent).join(ClientAgent,ClientAgent.agent_id==Agent.id)
            .filter(ClientAgent.client_id==client.id,ClientAgent.active.is_(True)).order_by(Agent.name).all())
    transactions=(GateTransaction.query.filter_by(client_id=client.id)
                  .order_by(GateTransaction.transaction_date.desc()).limit(80).all())
    total=sum((D(x.amount) for x in transactions),D(0))
    return render_template("master_data/client_detail.html",client=client,balance=balance,vehicles=vehicles,agents=agents,transactions=transactions,total=total)

@bp.route("/clients/<int:client_id>/edit",methods=["GET","POST"])
@permission_required("clients.manage")
def edit_client(client_id):
    client=db.session.get(Client,client_id)
    if not client: return ("غير موجود",404)
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    links=ClientAgent.query.filter_by(client_id=client.id).all(); selected={x.agent_id for x in links}
    if request.method=="POST":
        try:
            client.name=request.form["name"].strip()
            client.phone=request.form.get("phone"); client.identity_type=request.form.get("identity_type") or None
            client.identity_number=request.form.get("identity_number") or None
            client.address=request.form.get("address"); client.notes=request.form.get("notes")
            _save_party_identity(client,"client"); ensure_client_account(client)
            current={x.agent_id:x for x in links}; target={int(x) for x in request.form.getlist("agent_ids")}
            for aid,row in current.items(): row.active=aid in target
            for aid in target-current.keys(): db.session.add(ClientAgent(client_id=client.id,agent_id=aid,priority=1,active=True))

            existing_by_id={v.id:v for v in client.vehicles}
            submitted_ids={int(x) for x in request.form.getlist("vehicle_id") if x.isdigit()}
            submitted_plates=request.form.getlist("vehicle_plate_number")
            submitted_statuses=request.form.getlist("vehicle_registration_status")
            submitted_types=request.form.getlist("vehicle_type_id")
            submitted_notes=request.form.getlist("vehicle_notes")
            submitted_separators=request.form.getlist("vehicle_plate_separator")
            submitted_letters=request.form.getlist("vehicle_plate_letters")

            for i,type_id in enumerate(submitted_types):
                plate=(submitted_plates[i] if i<len(submitted_plates) else "").strip() or None
                status=(submitted_statuses[i] if i<len(submitted_statuses) else "registered").strip() or "registered"
                note=(submitted_notes[i] if i<len(submitted_notes) else "").strip() or None
                separator=(submitted_separators[i] if i<len(submitted_separators) else "").strip() or None
                letters=(submitted_letters[i] if i<len(submitted_letters) else "").strip() or None
                vid=request.form.getlist("vehicle_id")[i] if i<len(request.form.getlist("vehicle_id")) else ""
                if not type_id:
                    continue
                if status=="registered" and not plate:
                    raise ValueError("المركبة ذات اللوحة الجمركية يجب أن تحتوي على رقم لوحة")
                if vid.isdigit() and int(vid) in existing_by_id:
                    vehicle=existing_by_id[int(vid)]
                    if int(vehicle.client_id or 0)!=client.id:
                        raise ValueError("مركبة غير مرتبطة بالعميل")
                    vehicle.plate_number=plate
                    vehicle.plate_separator=separator
                    vehicle.plate_letters=letters
                    vehicle.registration_status=status
                    vehicle.vehicle_type_id=int(type_id)
                    vehicle.notes=note
                else:
                    vehicle=Vehicle(plate_number=plate,plate_separator=separator,plate_letters=letters,registration_status=status,vehicle_type_id=int(type_id),
                        client_id=client.id,notes=note,active=True)
                    db.session.add(vehicle)

            audit("update","client",client.id,client.name); db.session.commit(); flash("تم تحديث العميل والمركبات والوكلاء","success")
            return redirect(url_for("master_data.client_detail",client_id=client.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    vehicle_types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all()
    return render_template("master_data/client_form.html",client=client,agents=agents,selected=selected,vehicle_types=vehicle_types)

@bp.post("/clients/<int:client_id>/delete")
@permission_required("clients.manage")
def delete_client(client_id):
    client=db.session.get(Client,client_id)
    if not client: return ("غير موجود",404)
    client.active=False
    audit("deactivate","client",client.id,client.name); db.session.commit(); flash("تم إيقاف العميل مع حفظ تاريخه","success")
    return redirect(url_for("master_data.clients"))

@bp.post("/clients/<int:client_id>/toggle")
@permission_required("clients.manage")
def toggle_client(client_id):
    client=db.session.get(Client,client_id)
    if not client: return ("غير موجود",404)
    client.active=not client.active; audit("toggle","client",client.id,str(client.active)); db.session.commit()
    return redirect(url_for("master_data.clients"))

@bp.route("/vehicles",methods=["GET","POST"])
@permission_required("vehicles.view")
def vehicles():
    q=request.args.get("q","").strip()
    query=Vehicle.query
    if q:
        compact=q.replace(" ","").replace("-","").replace("/","")
        query=query.filter(or_(
            Vehicle.plate_number.ilike(f"%{q}%"),
            Vehicle.plate_separator.ilike(f"%{q}%"),
            Vehicle.plate_letters.ilike(f"%{q}%"),
            func.replace(func.replace(func.replace(Vehicle.plate_number," ",""),"-",""),"/","").ilike(f"%{compact}%"),
            Vehicle.registration_status.ilike(f"%{q}%"),
            Vehicle.client.has(Client.name.ilike(f"%{q}%"))
        ))
    rows=query.order_by(Vehicle.active.desc(),Vehicle.updated_at.desc()).all()
    types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all()
    all_vehicle_types=VehicleType.query.order_by(VehicleType.active.desc(),VehicleType.name).all()
    clients=Client.query.filter_by(active=True).order_by(Client.name).all()
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    if request.method=="POST":
        if not can("vehicles.manage"): return ("Forbidden",403)
        try:
            plate=request.form.get("plate_number","").strip() or None
            status=request.form.get("registration_status","registered").strip() or "registered"
            if status=="registered" and not plate:
                raise ValueError("أدخل رقم اللوحة أو اختر «بدون جمارك»")
            v=Vehicle(plate_number=plate,plate_separator=request.form.get("plate_separator") or None,
                plate_letters=request.form.get("plate_letters") or None,registration_status=status,
                vehicle_type_id=int(request.form["vehicle_type_id"]),
                client_id=int(request.form["client_id"]) if request.form.get("client_id") else None,notes=request.form.get("notes"))
            db.session.add(v); db.session.flush()
            for aid in {int(x) for x in request.form.getlist("agent_ids")}: db.session.add(VehicleAgent(vehicle_id=v.id,agent_id=aid,active=True))
            audit("create","vehicle",v.id,v.plate_number or "بدون جمارك"); db.session.commit(); flash("تم إضافة المركبة","success")
            return redirect(url_for("master_data.vehicles"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    selected_client_id=request.args.get("client_id",type=int)
    return render_template("master_data/vehicles.html",vehicles=rows,vehicle_types=types,all_vehicle_types=all_vehicle_types,clients=clients,agents=agents,can_manage=can("vehicles.manage"),q=q,selected_client_id=selected_client_id)

@bp.get("/vehicles/<int:vehicle_id>")
@permission_required("vehicles.view")
def vehicle_detail(vehicle_id):
    vehicle=db.session.get(Vehicle,vehicle_id)
    if not vehicle: return ("غير موجود",404)
    agents=(db.session.query(Agent).join(VehicleAgent,VehicleAgent.agent_id==Agent.id)
            .filter(VehicleAgent.vehicle_id==vehicle.id,VehicleAgent.active.is_(True)).order_by(Agent.name).all())
    tx=GateTransaction.query.filter_by(vehicle_id=vehicle.id).order_by(GateTransaction.transaction_date.desc()).limit(80).all()
    return render_template("master_data/vehicle_detail.html",vehicle=vehicle,agents=agents,transactions=tx)

@bp.route("/vehicles/<int:vehicle_id>/edit",methods=["GET","POST"])
@permission_required("vehicles.manage")
def edit_vehicle(vehicle_id):
    v=db.session.get(Vehicle,vehicle_id)
    if not v: return ("غير موجود",404)
    types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all()
    clients=Client.query.filter_by(active=True).order_by(Client.name).all(); agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    links=VehicleAgent.query.filter_by(vehicle_id=v.id).all(); selected={x.agent_id for x in links}
    if request.method=="POST":
        try:
            plate=request.form.get("plate_number","").strip() or None
            status=request.form.get("registration_status","registered").strip() or "registered"
            if status=="registered" and not plate:
                raise ValueError("أدخل رقم اللوحة أو اختر «بدون جمارك»")
            v.plate_number=plate; v.plate_separator=request.form.get("plate_separator") or None
            v.plate_letters=request.form.get("plate_letters") or None; v.registration_status=status
            v.vehicle_type_id=int(request.form["vehicle_type_id"])
            v.client_id=int(request.form["client_id"]) if request.form.get("client_id") else None; v.notes=request.form.get("notes")
            current={x.agent_id:x for x in links}; target={int(x) for x in request.form.getlist("agent_ids")}
            for aid,row in current.items(): row.active=aid in target
            for aid in target-current.keys(): db.session.add(VehicleAgent(vehicle_id=v.id,agent_id=aid,active=True))
            audit("update","vehicle",v.id,v.plate_number or "بدون جمارك"); db.session.commit(); flash("تم تحديث المركبة","success")
            return redirect(url_for("master_data.vehicle_detail",vehicle_id=v.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/vehicle_form.html",vehicle=v,vehicle_types=types,clients=clients,agents=agents,selected=selected)

@bp.post("/vehicles/<int:vehicle_id>/delete")
@permission_required("vehicles.manage")
def delete_vehicle(vehicle_id):
    v=db.session.get(Vehicle,vehicle_id)
    if not v: return ("غير موجود",404)
    v.active=False; audit("deactivate","vehicle",v.id,v.plate_number); db.session.commit()
    flash("تم إيقاف المركبة مع حفظ سجل الحركات","success"); return redirect(url_for("master_data.vehicles"))

@bp.post("/vehicles/<int:vehicle_id>/toggle")
@permission_required("vehicles.manage")
def toggle_vehicle(vehicle_id):
    v=db.session.get(Vehicle,vehicle_id)
    if not v: return ("غير موجود",404)
    v.active=not v.active; audit("toggle","vehicle",v.id,v.plate_number); db.session.commit(); return redirect(url_for("master_data.vehicles"))

@bp.route("/vehicle-types",methods=["POST"])
@permission_required("vehicles.manage")
def add_vehicle_type():
    name=request.form.get("name","").strip()
    if not name:
        flash("اكتب اسم نوع المركبة","danger")
        return redirect(url_for("master_data.vehicles"))
    try:
        existing=VehicleType.query.filter(func.lower(VehicleType.name)==name.lower()).first()
        if existing:
            raise ValueError("نوع المركبة موجود بالفعل")
        db.session.add(VehicleType(name=name,is_system=False,active=True))
        audit("create","vehicle_type",None,name)
        db.session.commit()
        flash(f"تم إضافة نوع المركبة: {name}","success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("master_data.vehicles"))


@bp.post("/vehicle-types/<int:type_id>/toggle")
@permission_required("vehicles.manage")
def toggle_vehicle_type(type_id):
    row=db.session.get(VehicleType,type_id)
    if not row:
        return ("غير موجود",404)
    row.active=not row.active
    audit("toggle","vehicle_type",row.id,f"{row.name}|{row.active}")
    db.session.commit()
    return redirect(url_for("master_data.vehicles"))


@bp.route("/employees",methods=["GET","POST"])
@permission_required("employees.view")
def employees():
    ensure_employees_for_users()
    q=request.args.get("q","").strip()
    query=Employee.query
    if q: query=query.filter(or_(Employee.full_name.ilike(f"%{q}%"),Employee.code.ilike(f"%{q}%"),Employee.phone.ilike(f"%{q}%"),Employee.job_title.ilike(f"%{q}%")))
    rows=query.order_by(Employee.active.desc(),Employee.code).all()
    if request.method=="POST":
        if not can("employees.manage"): return ("Forbidden",403)
        try:
            emp=Employee(code=next_code("EMP",Employee),full_name=request.form["full_name"].strip(),
                phone=request.form.get("phone","").strip() or None,identity_number=request.form.get("identity_number") or None,
                gender=request.form.get("gender") or None,employment_type=request.form.get("employment_type") or "دوام كامل",
                weekly_hours=D(request.form.get("weekly_hours","48")),job_title=request.form.get("job_title") or "موظف",
                monthly_salary=D(request.form.get("monthly_salary","0")),
                hire_date=date.fromisoformat(request.form.get("hire_date") or date.today().isoformat()),
                work_days="0,1,2,3,4,5",notes=request.form.get("notes"))
            db.session.add(emp); db.session.flush(); ensure_employee_account(emp); ensure_employee_payroll_account(emp)
            _save_identity_image(emp); _save_employee_login(emp)
            audit("create","employee",emp.id,emp.full_name); db.session.commit()
            flash("تم إضافة الموظف والملف المالي وحساب الدخول إن تم إدخاله","success")
            return redirect(url_for("master_data.employee_detail",employee_id=emp.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/employees.html",employees=rows,can_manage=can("employees.manage"),q=q,roles=[r.value for r in Role],role_labels=ROLE_LABELS,weekdays=WEEKDAYS)

@bp.post("/employees/fines")
@permission_required("employees.manage")
def add_employee_fine():
    try:
        employee_id=request.form.get("employee_id",type=int)
        employee=db.session.get(Employee,employee_id)
        if not employee or not employee.active:
            raise ValueError("اختر موظفًا نشطًا")
        amount=D(request.form.get("amount","0"))
        if amount<=0:
            raise ValueError("مبلغ الغرامة يجب أن يكون أكبر من صفر")
        reason=request.form.get("reason","").strip()
        if not reason:
            raise ValueError("بيان الغرامة مطلوب")
        fine_date=date.fromisoformat(request.form.get("fine_date") or date.today().isoformat())
        ensure_employee_account(employee)
        revenue=get_system_account("employee_fines_revenue")
        fine=EmployeeFine(employee_id=employee.id,fine_date=fine_date,amount=amount,reason=reason,created_by_id=current_user.id,journal_entry_id=None)
        db.session.add(fine)
        db.session.flush()
        entry=create_posted_entry(
            description=f"غرامة/مخالفة موظف: {employee.full_name} — {reason}",
            entry_date=fine_date,created_by_id=current_user.id,
            source_type="employee_fine",source_id=fine.id,prefix="FINE",
            lines=[{"account":employee.account,"debit":amount},{"account":revenue,"credit":amount}],
            audit=f"غرامة موظف {employee.full_name}: {amount}"
        )
        fine.journal_entry_id=entry.id
        audit("create","employee_fine",fine.id,f"{employee.full_name}|{amount}|{reason}")
        db.session.commit()
        flash(f"تم تسجيل غرامة الموظف {employee.full_name} وترحيل القيد {entry.number}","success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc),"danger")
    return redirect(url_for("master_data.employees",q=request.form.get("return_q","")))


@bp.get("/employees/<int:employee_id>")
@permission_required("employees.view")
def employee_detail(employee_id):
    emp=db.session.get(Employee,employee_id)
    if not emp: return ("غير موجود",404)
    custody=account_balance(emp.account_id) if emp.account_id else D(0)
    payroll_due=account_balance(emp.payroll_account_id) if emp.payroll_account_id else D(0)
    shifts=Shift.query.filter_by(collector_id=emp.user.id if emp.user else -1).order_by(Shift.opened_at.desc()).limit(60).all()
    audits=AuditLog.query.filter_by(user_id=emp.user.id if emp.user else -1).order_by(AuditLog.created_at.desc()).limit(30).all()
    gates=GateTransaction.query.filter_by(collector_id=emp.user.id if emp.user else -1).order_by(GateTransaction.transaction_date.desc()).limit(30).all()
    payroll_lines=(PayrollLine.query.filter_by(employee_id=emp.id).order_by(PayrollLine.id.desc()).limit(24).all())
    return render_template("master_data/employee_detail.html",employee=emp,custody=custody,payroll_due=payroll_due,shifts=shifts,audits=audits,gates=gates,payroll_lines=payroll_lines,fines=EmployeeFine.query.filter_by(employee_id=emp.id).order_by(EmployeeFine.fine_date.desc(),EmployeeFine.id.desc()).limit(30).all(),weekdays=WEEKDAYS,role_labels=ROLE_LABELS)

@bp.route("/employees/<int:employee_id>/edit",methods=["GET","POST"])
@permission_required("employees.manage")
def edit_employee(employee_id):
    emp=db.session.get(Employee,employee_id)
    if not emp: return ("غير موجود",404)
    if request.method=="POST":
        try:
            emp.full_name=request.form["full_name"].strip()
            emp.phone=request.form.get("phone","").strip() or None; emp.identity_number=request.form.get("identity_number") or None
            emp.gender=request.form.get("gender") or None; emp.employment_type=request.form.get("employment_type") or "دوام كامل"
            emp.weekly_hours=D(request.form.get("weekly_hours","48")); emp.job_title=request.form.get("job_title") or "موظف"
            emp.monthly_salary=D(request.form.get("monthly_salary","0")); emp.hire_date=date.fromisoformat(request.form.get("hire_date") or date.today().isoformat())
            emp.notes=request.form.get("notes")
            ensure_employee_account(emp); ensure_employee_payroll_account(emp)
            _save_identity_image(emp); _save_employee_login(emp)
            if emp.user: emp.user.full_name=emp.full_name; emp.user.phone=emp.phone; emp.user.active=emp.active
            audit("update","employee",emp.id,emp.full_name); db.session.commit()
            flash("تم تحديث ملف الموظف","success"); return redirect(url_for("master_data.employee_detail",employee_id=emp.id))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/employee_form.html",employee=emp,roles=[r.value for r in Role],role_labels=ROLE_LABELS,weekdays=WEEKDAYS)

@bp.post("/employees/<int:employee_id>/delete")
@permission_required("employees.manage")
def delete_employee(employee_id):
    emp=db.session.get(Employee,employee_id)
    if not emp: return ("غير موجود",404)
    emp.active=False
    if emp.user: emp.user.active=False
    audit("deactivate","employee",emp.id,emp.full_name); db.session.commit()
    flash("تم إيقاف الموظف وحفظ الرواتب والقيود السابقة","success")
    return redirect(url_for("master_data.employees"))

@bp.post("/employees/<int:employee_id>/toggle")
@permission_required("employees.manage")
def toggle_employee(employee_id):
    emp=db.session.get(Employee,employee_id)
    if not emp: return ("غير موجود",404)
    emp.active=not emp.active
    if emp.user: emp.user.active=emp.active
    audit("toggle","employee",emp.id,str(emp.active)); db.session.commit(); return redirect(url_for("master_data.employees"))

@bp.post("/employees/<int:employee_id>/schedule")
@permission_required("employees.manage")
def add_schedule(employee_id):
    emp=db.session.get(Employee,employee_id)
    if not emp: return ("غير موجود",404)
    try:
        weekday=int(request.form.get("weekday","0"))
        if weekday not in range(7): raise ValueError("اليوم غير صالح")
        shift_name=request.form.get("shift_name","دوام").strip() or "دوام"
        row=EmployeeSchedule(employee_id=emp.id,weekday=weekday,shift_name=shift_name,
            start_time=time.fromisoformat(request.form["start_time"]) if request.form.get("start_time") else None,
            end_time=time.fromisoformat(request.form["end_time"]) if request.form.get("end_time") else None,active=True)
        db.session.add(row); _sync_work_days(emp); audit("create","employee_schedule",emp.id,f"{weekday}|{shift_name}"); db.session.commit()
        flash("تم حفظ جدول دوام الموظف","success")
    except Exception as exc:
        db.session.rollback(); flash(str(exc),"danger")
    return redirect(url_for("master_data.employee_detail",employee_id=employee_id))

@bp.post("/employees/schedule/<int:schedule_id>/delete")
@permission_required("employees.manage")
def delete_schedule(schedule_id):
    row=db.session.get(EmployeeSchedule,schedule_id)
    if not row: return ("غير موجود",404)
    emp=row.employee
    db.session.delete(row); db.session.flush(); _sync_work_days(emp)
    audit("delete","employee_schedule",emp.id,str(schedule_id)); db.session.commit()
    return redirect(url_for("master_data.employee_detail",employee_id=emp.id))

@bp.get("/employees/<int:employee_id>/identity")
@permission_required("employees.view")
def employee_identity(employee_id):
    emp=db.session.get(Employee,employee_id)
    if not emp or not emp.identity_image: return ("الملف غير موجود",404)
    rel=Path(emp.identity_image)
    if rel.parts[:1] != ("employee_ids",): return ("الملف غير موجود",404)
    folder=Path(current_app.config["UPLOAD_FOLDER"]) / "employee_ids"
    return send_from_directory(folder,rel.name,as_attachment=False)


@bp.get("/agents/<int:agent_id>/identity")
@permission_required("agents.view")
def agent_identity(agent_id):
    agent=db.session.get(Agent,agent_id)
    if not agent or not agent.identity_image: return ("الملف غير موجود",404)
    rel=Path(agent.identity_image)
    if rel.parts[:1] != ("party_ids",): return ("الملف غير موجود",404)
    folder=Path(current_app.config["UPLOAD_FOLDER"]) / "party_ids"
    return send_from_directory(folder,rel.name,as_attachment=False)

@bp.get("/clients/<int:client_id>/identity")
@permission_required("clients.view")
def client_identity(client_id):
    client=db.session.get(Client,client_id)
    if not client or not client.identity_image: return ("الملف غير موجود",404)
    rel=Path(client.identity_image)
    if rel.parts[:1] != ("party_ids",): return ("الملف غير موجود",404)
    folder=Path(current_app.config["UPLOAD_FOLDER"]) / "party_ids"
    return send_from_directory(folder,rel.name,as_attachment=False)
