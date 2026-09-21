from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from ..extensions import db
from ..models import Agent, Client, ClientAgent, Employee, User, Vehicle, VehicleAgent, VehicleType
from ..permissions import can, permission_required
from ..services.audit import audit
from ..services.accounts import ensure_agent_account, ensure_client_account, ensure_employee_account, ensure_employee_payroll_account

bp=Blueprint("master_data",__name__)

def next_code(prefix, model):
    return f"{prefix}-{db.session.query(model).count()+1:05d}"

@bp.route("/agents",methods=["GET","POST"])
@permission_required("agents.view")
def agents():
    rows=Agent.query.order_by(Agent.active.desc(),Agent.name).all()
    if request.method=="POST":
        if not can("agents.manage"): return ("Forbidden",403)
        try:
            agent=Agent(code=request.form.get("code") or next_code("AG",Agent),name=request.form["name"].strip(),
                phone=request.form.get("phone"),notes=request.form.get("notes"),active=True)
            db.session.add(agent); db.session.flush(); ensure_agent_account(agent)
            audit("create","agent",agent.id,agent.name); db.session.commit(); flash("تم إضافة الوكيل وإنشاء حسابه","success")
            return redirect(url_for("master_data.agents"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/agents.html",agents=rows,can_manage=can("agents.manage"))

@bp.route("/agents/<int:agent_id>/edit",methods=["GET","POST"])
@permission_required("agents.manage")
def edit_agent(agent_id):
    agent=db.session.get(Agent,agent_id)
    if request.method=="POST":
        try:
            agent.code=request.form["code"]; agent.name=request.form["name"].strip()
            agent.phone=request.form.get("phone"); agent.notes=request.form.get("notes")
            ensure_agent_account(agent); audit("update","agent",agent.id,agent.name); db.session.commit(); flash("تم تحديث الوكيل","success")
            return redirect(url_for("master_data.agents"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/agent_form.html",agent=agent)

@bp.post("/agents/<int:agent_id>/toggle")
@permission_required("agents.manage")
def toggle_agent(agent_id):
    agent=db.session.get(Agent,agent_id); agent.active=not agent.active
    audit("toggle","agent",agent.id,str(agent.active)); db.session.commit()
    return redirect(url_for("master_data.agents"))

@bp.route("/clients",methods=["GET","POST"])
@permission_required("clients.view")
def clients():
    rows=Client.query.order_by(Client.active.desc(),Client.name).all()
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    if request.method=="POST":
        if not can("clients.manage"): return ("Forbidden",403)
        try:
            client=Client(code=request.form.get("code") or next_code("CL",Client),name=request.form["name"].strip(),
                phone=request.form.get("phone"),address=request.form.get("address"),notes=request.form.get("notes"),active=True)
            db.session.add(client); db.session.flush(); ensure_client_account(client)
            selected={int(x) for x in request.form.getlist("agent_ids")}
            for aid in selected:
                db.session.add(ClientAgent(client_id=client.id,agent_id=aid,priority=1))
            audit("create","client",client.id,client.name); db.session.commit(); flash("تم إضافة العميل وحسابه وروابط الوكلاء","success")
            return redirect(url_for("master_data.clients"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/clients.html",clients=rows,agents=agents,can_manage=can("clients.manage"))

@bp.route("/clients/<int:client_id>/edit",methods=["GET","POST"])
@permission_required("clients.manage")
def edit_client(client_id):
    client=db.session.get(Client,client_id); agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    links=ClientAgent.query.filter_by(client_id=client.id).all(); selected={x.agent_id for x in links}
    if request.method=="POST":
        try:
            client.code=request.form["code"]; client.name=request.form["name"].strip()
            client.phone=request.form.get("phone"); client.address=request.form.get("address"); client.notes=request.form.get("notes")
            ensure_client_account(client)
            current={x.agent_id:x for x in links}; target={int(x) for x in request.form.getlist("agent_ids")}
            for aid,row in current.items():
                row.active=aid in target
            for aid in target-current.keys():
                db.session.add(ClientAgent(client_id=client.id,agent_id=aid,priority=1,active=True))
            audit("update","client",client.id,client.name); db.session.commit(); flash("تم تحديث العميل والوكلاء المرتبطين","success")
            return redirect(url_for("master_data.clients"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/client_form.html",client=client,agents=agents,selected=selected)

@bp.post("/clients/<int:client_id>/toggle")
@permission_required("clients.manage")
def toggle_client(client_id):
    client=db.session.get(Client,client_id); client.active=not client.active
    audit("toggle","client",client.id,str(client.active)); db.session.commit()
    return redirect(url_for("master_data.clients"))

@bp.route("/vehicles",methods=["GET","POST"])
@permission_required("vehicles.view")
def vehicles():
    rows=Vehicle.query.order_by(Vehicle.active.desc(),Vehicle.updated_at.desc()).all()
    types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all()
    clients=Client.query.filter_by(active=True).order_by(Client.name).all()
    agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    if request.method=="POST":
        if not can("vehicles.manage"): return ("Forbidden",403)
        try:
            v=Vehicle(plate_number=request.form["plate_number"].strip(),plate_separator=request.form.get("plate_separator") or None,
                plate_letters=request.form.get("plate_letters") or None,vehicle_type_id=int(request.form["vehicle_type_id"]),
                client_id=int(request.form["client_id"]) if request.form.get("client_id") else None,notes=request.form.get("notes"))
            db.session.add(v); db.session.flush()
            for aid in {int(x) for x in request.form.getlist("agent_ids")}: db.session.add(VehicleAgent(vehicle_id=v.id,agent_id=aid,active=True))
            audit("create","vehicle",v.id,v.plate_number); db.session.commit(); flash("تم إضافة المركبة","success")
            return redirect(url_for("master_data.vehicles"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/vehicles.html",vehicles=rows,vehicle_types=types,clients=clients,agents=agents,can_manage=can("vehicles.manage"))

@bp.route("/vehicles/<int:vehicle_id>/edit",methods=["GET","POST"])
@permission_required("vehicles.manage")
def edit_vehicle(vehicle_id):
    v=db.session.get(Vehicle,vehicle_id); types=VehicleType.query.filter_by(active=True).order_by(VehicleType.name).all()
    clients=Client.query.filter_by(active=True).order_by(Client.name).all(); agents=Agent.query.filter_by(active=True).order_by(Agent.name).all()
    links=VehicleAgent.query.filter_by(vehicle_id=v.id).all(); selected={x.agent_id for x in links}
    if request.method=="POST":
        try:
            v.plate_number=request.form["plate_number"].strip(); v.plate_separator=request.form.get("plate_separator") or None
            v.plate_letters=request.form.get("plate_letters") or None; v.vehicle_type_id=int(request.form["vehicle_type_id"])
            v.client_id=int(request.form["client_id"]) if request.form.get("client_id") else None; v.notes=request.form.get("notes")
            current={x.agent_id:x for x in links}; target={int(x) for x in request.form.getlist("agent_ids")}
            for aid,row in current.items(): row.active=aid in target
            for aid in target-current.keys(): db.session.add(VehicleAgent(vehicle_id=v.id,agent_id=aid,active=True))
            audit("update","vehicle",v.id,v.plate_number); db.session.commit(); flash("تم تحديث المركبة","success")
            return redirect(url_for("master_data.vehicles"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/vehicle_form.html",vehicle=v,vehicle_types=types,clients=clients,agents=agents,selected=selected)

@bp.post("/vehicles/<int:vehicle_id>/toggle")
@permission_required("vehicles.manage")
def toggle_vehicle(vehicle_id):
    v=db.session.get(Vehicle,vehicle_id); v.active=not v.active
    audit("toggle","vehicle",v.id,v.plate_number); db.session.commit()
    return redirect(url_for("master_data.vehicles"))

@bp.route("/employees",methods=["GET","POST"])
@permission_required("employees.view")
def employees():
    rows=Employee.query.order_by(Employee.active.desc(),Employee.code).all()
    if request.method=="POST":
        if not can("employees.manage"): return ("Forbidden",403)
        try:
            emp=Employee(code=request.form.get("code") or next_code("EMP",Employee),full_name=request.form["full_name"].strip(),
                phone=request.form.get("phone"),job_title=request.form.get("job_title") or "موظف",
                monthly_salary=D(request.form.get("monthly_salary","0")),hire_date=date.fromisoformat(request.form.get("hire_date") or date.today().isoformat()))
            db.session.add(emp); db.session.flush(); ensure_employee_account(emp); ensure_employee_payroll_account(emp)
            audit("create","employee",emp.id,emp.full_name); db.session.commit(); flash("تم إضافة الموظف وحساب العهدة والراتب","success")
            return redirect(url_for("master_data.employees"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/employees.html",employees=rows,can_manage=can("employees.manage"))

@bp.route("/employees/<int:employee_id>/edit",methods=["GET","POST"])
@permission_required("employees.manage")
def edit_employee(employee_id):
    emp=db.session.get(Employee,employee_id)
    if request.method=="POST":
        try:
            emp.code=request.form["code"]; emp.full_name=request.form["full_name"].strip(); emp.phone=request.form.get("phone")
            emp.job_title=request.form.get("job_title") or "موظف"; emp.monthly_salary=D(request.form.get("monthly_salary","0"))
            emp.hire_date=date.fromisoformat(request.form.get("hire_date") or date.today().isoformat())
            ensure_employee_account(emp); ensure_employee_payroll_account(emp)
            audit("update","employee",emp.id,emp.full_name); db.session.commit(); flash("تم تحديث الموظف","success")
            return redirect(url_for("master_data.employees"))
        except Exception as exc:
            db.session.rollback(); flash(str(exc),"danger")
    return render_template("master_data/employee_form.html",employee=emp)

@bp.post("/employees/<int:employee_id>/toggle")
@permission_required("employees.manage")
def toggle_employee(employee_id):
    emp=db.session.get(Employee,employee_id); emp.active=not emp.active
    audit("toggle","employee",emp.id,str(emp.active)); db.session.commit()
    return redirect(url_for("master_data.employees"))

def D(value):
    from decimal import Decimal
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))
