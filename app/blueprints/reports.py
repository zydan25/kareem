import csv
from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, render_template, request
from sqlalchemy import and_, func, or_

from ..extensions import db
from ..models import Account, Agent, Client, Employee, Expense, GateTransaction, JournalEntry, JournalLine, Shift, User
from ..permissions import permission_required
from ..services.accounting import account_balance, D

bp=Blueprint("reports",__name__,url_prefix="/reports")
LOCAL_TZ=ZoneInfo("Asia/Aden")

def parse_dates():
    today=datetime.now(LOCAL_TZ).date()
    start=date.fromisoformat(request.args.get("start")) if request.args.get("start") else today
    end=date.fromisoformat(request.args.get("end")) if request.args.get("end") else start
    if end<start: start,end=end,start
    return start,end

def period_query(start,end):
    start_dt=datetime.combine(start,datetime.min.time(),LOCAL_TZ)
    end_dt=datetime.combine(end+timedelta(days=1),datetime.min.time(),LOCAL_TZ)
    return start_dt.astimezone(ZoneInfo("UTC")),end_dt.astimezone(ZoneInfo("UTC"))

@bp.get("/")
@permission_required("reports.view")
def index():
    start,end=parse_dates()
    return render_template("reports/index.html",start=start,end=end)

@bp.get("/gate")
@permission_required("reports.view")
def gate():
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    q=GateTransaction.query.filter(GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt)
    if request.args.get("collector_id"): q=q.filter_by(collector_id=int(request.args["collector_id"]))
    if request.args.get("agent_id"): q=q.filter_by(agent_id=int(request.args["agent_id"]))
    if request.args.get("client_id"): q=q.filter_by(client_id=int(request.args["client_id"]))
    if request.args.get("shift_id"): q=q.filter_by(shift_id=int(request.args["shift_id"]))
    rows=q.order_by(GateTransaction.transaction_date.desc()).all()
    total=sum((D(x.amount) for x in rows),D(0))
    entry_total=sum((D(x.amount) for x in rows if x.direction=="entry"),D(0))
    exit_count=sum((1 for x in rows if x.direction=="exit"),0)
    return render_template("reports/gate.html",rows=rows,start=start,end=end,total=total,entry_total=entry_total,exit_count=exit_count,
        collectors=User.query.filter_by(active=True).order_by(User.full_name).all(),
        agents=Agent.query.filter_by(active=True).order_by(Agent.name).all(),
        shifts=Shift.query.order_by(Shift.opened_at.desc()).limit(150).all())

@bp.get("/gate.csv")
@permission_required("reports.export")
def gate_csv():
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    q=GateTransaction.query.filter(GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt)
    if request.args.get("collector_id"): q=q.filter_by(collector_id=int(request.args["collector_id"]))
    if request.args.get("agent_id"): q=q.filter_by(agent_id=int(request.args["agent_id"]))
    if request.args.get("shift_id"): q=q.filter_by(shift_id=int(request.args["shift_id"]))
    rows=q.order_by(GateTransaction.transaction_date).all()
    out=StringIO(); w=csv.writer(out); w.writerow(["السند","التاريخ","الحركة","اللوحة","العميل","الوكيل","المتحصل","المبلغ"])
    for x in rows:
        w.writerow([x.receipt_number,x.transaction_date.isoformat(),x.direction,
                    x.vehicle.plate_number,x.client.name if x.client else "",x.agent.name if x.agent else "",
                    x.collector.full_name,x.amount])
    return Response("\ufeff"+out.getvalue(),mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":f"attachment; filename=gate-{start}-to-{end}.csv"})

@bp.get("/collectors")
@permission_required("reports.view")
def collectors():
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    rows=(db.session.query(User.id,User.full_name,User.role,func.count(GateTransaction.id).label("count"),
        func.coalesce(func.sum(GateTransaction.amount),0).label("total"))
        .outerjoin(GateTransaction,(GateTransaction.collector_id==User.id)&
                   (GateTransaction.transaction_date>=start_dt)&(GateTransaction.transaction_date<end_dt)&
                   (GateTransaction.direction=="entry")&(GateTransaction.amount>0)&
                   (GateTransaction.counted_for_work.is_(True)))
        .filter(User.role=="collector").group_by(User.id,User.full_name,User.role)
        .order_by(User.full_name).all())
    return render_template("reports/collectors.html",rows=rows,start=start,end=end)

def _account_period_rows(start,end, account_type=None):
    q=(db.session.query(Account.id,Account.code,Account.name,Account.account_type,
        func.coalesce(func.sum(JournalLine.debit),0).label("debit"),
        func.coalesce(func.sum(JournalLine.credit),0).label("credit"))
       .outerjoin(JournalLine,JournalLine.account_id==Account.id)
       .outerjoin(JournalEntry,JournalEntry.id==JournalLine.entry_id)
       .filter(Account.is_group.is_(False))
       .filter(or_(JournalEntry.id.is_(None),and_(JournalEntry.status=="posted",
                                                   JournalEntry.entry_date>=start,
                                                   JournalEntry.entry_date<=end))))
    if account_type: q=q.filter(Account.account_type==account_type)
    q=q.group_by(Account.id,Account.code,Account.name,Account.account_type).order_by(Account.code)
    result=[]
    for r in q.all():
        opening=account_balance(r.id,end=start-timedelta(days=1))
        debit=D(r.debit); credit=D(r.credit); closing=opening+debit-credit
        result.append({"id":r.id,"code":r.code,"name":r.name,"account_type":r.account_type,
                       "opening":opening,"debit":debit,"credit":credit,"closing":closing})
    return result

@bp.get("/accounts")
@permission_required("reports.view")
def accounts_report():
    start,end=parse_dates()
    rows=_account_period_rows(start,end)
    return render_template("reports/accounts.html",rows=rows,start=start,end=end)

@bp.get("/general-ledger")
@permission_required("reports.view")
def general_ledger():
    start,end=parse_dates()
    account_id=request.args.get("account_id",type=int)
    accounts=Account.query.filter_by(is_group=False,active=True).order_by(Account.code).all()
    rows=[]; opening=D(0); closing=D(0); account=None
    if account_id:
        account=db.session.get(Account,account_id)
        lines=(db.session.query(JournalLine).join(JournalEntry)
            .filter(JournalLine.account_id==account_id,JournalEntry.status=="posted",
                    JournalEntry.entry_date>=start,JournalEntry.entry_date<=end)
            .order_by(JournalEntry.entry_date,JournalLine.id).all())
        opening=account_balance(account_id,end=start-timedelta(days=1))
        running=opening
        for line in lines:
            running += D(line.debit)-D(line.credit)
            rows.append((line,running))
        closing=running
    return render_template("reports/general_ledger.html",accounts=accounts,rows=rows,account=account,account_id=account_id,start=start,end=end,opening=opening,closing=closing)

@bp.get("/income-expenses")
@permission_required("reports.view")
def income_expenses():
    start,end=parse_dates()
    revenues=_account_period_rows(start,end,"revenue")
    expenses=_account_period_rows(start,end,"expense")
    revenue_total=sum((r["credit"]-r["debit"] for r in revenues),D(0))
    expense_total=sum((r["debit"]-r["credit"] for r in expenses),D(0))
    net=revenue_total-expense_total
    return render_template("reports/income_expenses.html",revenues=revenues,expenses=expenses,
                           revenue_total=revenue_total,expense_total=expense_total,net=net,start=start,end=end)

@bp.get("/shifts/<int:shift_id>")
@permission_required("reports.view")
def shift_report(shift_id):
    shift=db.session.get(Shift,shift_id)
    if not shift: return ("الوردية غير موجودة",404)
    rows=GateTransaction.query.filter_by(shift_id=shift.id).order_by(GateTransaction.transaction_date).all()
    total=sum((D(x.amount) for x in rows),D(0))
    return render_template("reports/shift.html",shift=shift,rows=rows,total=total)

@bp.get("/account/<int:account_id>")
@permission_required("reports.view")
def account_statement(account_id):
    account=db.session.get(Account,account_id)
    if not account: return ("الحساب غير موجود",404)
    start,end=parse_dates()
    lines=(db.session.query(JournalLine).join(JournalEntry)
        .filter(JournalLine.account_id==account_id,JournalEntry.status=="posted",JournalEntry.entry_date>=start,JournalEntry.entry_date<=end)
        .order_by(JournalEntry.entry_date,JournalLine.id).all())
    opening=account_balance(account_id,end=start-timedelta(days=1))
    running=opening; balance_lines=[]
    for line in lines:
        running += D(line.debit)-D(line.credit)
        balance_lines.append((line,running))
    return render_template("reports/account_statement.html",account=account,lines=balance_lines,start=start,end=end,opening=opening,
                           debit_total=sum((D(x.debit) for x in lines),D(0)),
                           credit_total=sum((D(x.credit) for x in lines),D(0)),closing=running)



@bp.get("/custody")
@permission_required("reports.view")
def custody():
    start,end=parse_dates()
    custody_root=Account.query.filter_by(system_key="collector_root").one_or_none()
    rows=[]
    if custody_root:
        accounts=Account.query.filter_by(account_type="asset",is_group=False,active=True,parent_id=custody_root.id).order_by(Account.code).all()
        for account in accounts:
            period_lines=(db.session.query(JournalLine).join(JournalEntry)
                          .filter(JournalLine.account_id==account.id,JournalEntry.status=="posted",
                                  JournalEntry.entry_date>=start,JournalEntry.entry_date<=end).all())
            rows.append({
                "account":account,
                "opening":account_balance(account.id,end=start-timedelta(days=1)),
                "period_debit":sum((D(x.debit) for x in period_lines),D(0)),
                "period_credit":sum((D(x.credit) for x in period_lines),D(0)),
                "balance":account_balance(account.id),
            })
    from ..models import Settlement
    settlements=Settlement.query.filter(Settlement.settlement_date>=start,Settlement.settlement_date<=end).order_by(Settlement.id.desc()).all()
    return render_template("reports/custody.html",rows=rows,settlements=settlements,start=start,end=end)



def _period_for_shortcut(kind):
    today=datetime.now(LOCAL_TZ).date()
    if kind=="daily": return today,today
    if kind=="weekly":
        return today-timedelta(days=today.weekday()),today
    if kind=="monthly":
        return today.replace(day=1),today
    return today,today

@bp.get("/daily")
@permission_required("reports.view")
def daily():
    start,end=_period_for_shortcut("daily")
    from flask import redirect, url_for
    return redirect(url_for("reports.period",start=start.isoformat(),end=end.isoformat(),kind="يومي"))

@bp.get("/weekly")
@permission_required("reports.view")
def weekly():
    start,end=_period_for_shortcut("weekly")
    from flask import redirect, url_for
    return redirect(url_for("reports.period",start=start.isoformat(),end=end.isoformat(),kind="أسبوعي"))

@bp.get("/monthly")
@permission_required("reports.view")
def monthly():
    start,end=_period_for_shortcut("monthly")
    from flask import redirect, url_for
    return redirect(url_for("reports.period",start=start.isoformat(),end=end.isoformat(),kind="شهري"))

@bp.get("/period")
@permission_required("reports.view")
def period():
    start,end=parse_dates()
    start_dt,end_dt=period_query(start,end)
    gates=GateTransaction.query.filter(GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt).all()
    expenses=Expense.query.filter(Expense.expense_date>=start,Expense.expense_date<=end).all()
    paid_rents=__import__("app.models",fromlist=["AgentRent"]).AgentRent.query.filter(
        __import__("app.models",fromlist=["AgentRent"]).AgentRent.status=="paid"
    ).filter(
        __import__("app.models",fromlist=["AgentRent"]).AgentRent.rent_month>=start,
        __import__("app.models",fromlist=["AgentRent"]).AgentRent.rent_month<=end
    ).all()
    entry_total=sum((D(x.amount) for x in gates if x.direction=="entry"),D(0))
    exit_total=sum((D(x.amount) for x in gates if x.direction=="exit"),D(0))
    expense_total=sum((D(x.amount) for x in expenses),D(0))
    rent_total=sum((D(x.amount) for x in paid_rents),D(0))
    return render_template("reports/period.html",start=start,end=end,kind=request.args.get("kind","مخصص"),
        gate_count=len(gates),entry_total=entry_total,exit_total=exit_total,
        expense_total=expense_total,rent_total=rent_total,total_expenses=len(expenses))

@bp.get("/clients/<int:client_id>")
@permission_required("reports.view")
def client_report(client_id):
    client=db.session.get(Client,client_id)
    if not client: return ("العميل غير موجود",404)
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    rows=GateTransaction.query.filter_by(client_id=client.id).filter(
        GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt
    ).order_by(GateTransaction.transaction_date.desc()).all()
    return render_template("reports/entity_report.html",title="تقرير العميل",entity=client,entity_type="عميل",
        start=start,end=end,rows=rows,balance=account_balance(client.account_id) if client.account_id else D(0))

@bp.get("/agents/<int:agent_id>")
@permission_required("reports.view")
def agent_report(agent_id):
    agent=db.session.get(Agent,agent_id)
    if not agent: return ("الوكيل غير موجود",404)
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    rows=GateTransaction.query.filter_by(agent_id=agent.id).filter(
        GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt
    ).order_by(GateTransaction.transaction_date.desc()).all()
    from ..models import AgentRent
    rents=AgentRent.query.filter_by(agent_id=agent.id).filter(AgentRent.rent_month>=start,AgentRent.rent_month<=end).order_by(AgentRent.rent_month.desc()).all()
    return render_template("reports/agent_report.html",agent=agent,start=start,end=end,rows=rows,rents=rents,
        balance=account_balance(agent.account_id) if agent.account_id else D(0))

@bp.get("/employees/<int:employee_id>")
@permission_required("reports.view")
def employee_report(employee_id):
    employee=db.session.get(Employee,employee_id)
    if not employee: return ("الموظف غير موجود",404)
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    shifts=Shift.query.filter_by(collector_id=employee.user.id if employee.user else -1).filter(
        Shift.opened_at<end_dt
    ).order_by(Shift.opened_at.desc()).all()
    gates=GateTransaction.query.filter_by(collector_id=employee.user.id if employee.user else -1).filter(
        GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt
    ).order_by(GateTransaction.transaction_date.desc()).all()
    audits=__import__("app.models",fromlist=["AuditLog"]).AuditLog.query.filter_by(user_id=employee.user.id if employee.user else -1).filter(
        __import__("app.models",fromlist=["AuditLog"]).AuditLog.created_at>=start_dt,
        __import__("app.models",fromlist=["AuditLog"]).AuditLog.created_at<end_dt
    ).order_by(__import__("app.models",fromlist=["AuditLog"]).AuditLog.created_at.desc()).limit(100).all()
    return render_template("reports/employee_report.html",employee=employee,start=start,end=end,shifts=shifts,gates=gates,audits=audits,
        custody=account_balance(employee.account_id) if employee.account_id else D(0),
        payroll_due=account_balance(employee.payroll_account_id) if employee.payroll_account_id else D(0))

@bp.get("/employees")
@permission_required("reports.view")
def employees_report():
    start,end=parse_dates(); start_dt,end_dt=period_query(start,end)
    employees=Employee.query.order_by(Employee.active.desc(),Employee.full_name).all()
    rows=[]
    for e in employees:
        uid=e.user.id if e.user else -1
        gates=GateTransaction.query.filter_by(collector_id=uid).filter(
            GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt,
            GateTransaction.direction.in_(["entry","exit"])).all()
        shifts=Shift.query.filter_by(collector_id=uid).filter(Shift.opened_at<end_dt).filter(
            (Shift.closed_at.is_(None)) | (Shift.closed_at>=start_dt)).all()
        rows.append({"employee":e,"gate_count":len(gates),"total":sum((D(x.amount) for x in gates),D(0)),"shifts":len(shifts),
                     "custody":account_balance(e.account_id) if e.account_id else D(0)})
    return render_template("reports/employees.html",rows=rows,start=start,end=end)

@bp.get("/expenses")
@permission_required("reports.view")
def expenses_report():
    start,end=parse_dates()
    rows=Expense.query.filter(Expense.expense_date>=start,Expense.expense_date<=end).order_by(Expense.expense_date.desc(),Expense.id.desc()).all()
    total=sum((D(x.amount) for x in rows),D(0))
    return render_template("reports/expenses.html",rows=rows,start=start,end=end,total=total)

@bp.get("/trial-balance")
@permission_required("reports.view")
def trial_balance():
    start,end=parse_dates()
    rows=_account_period_rows(start,end)
    debit_total=sum((r["debit"] for r in rows),D(0))
    credit_total=sum((r["credit"] for r in rows),D(0))
    return render_template("reports/trial_balance.html",rows=rows,start=start,end=end,debit_total=debit_total,credit_total=credit_total)
