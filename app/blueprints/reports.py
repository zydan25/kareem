import csv
from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, render_template, request
from sqlalchemy import func

from ..extensions import db
from ..models import Account, Agent, GateTransaction, JournalEntry, JournalLine, Shift, User
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
    rows=GateTransaction.query.filter(GateTransaction.transaction_date>=start_dt,GateTransaction.transaction_date<end_dt).order_by(GateTransaction.transaction_date).all()
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
       .outerjoin(JournalEntry,(JournalEntry.id==JournalLine.entry_id)&(JournalEntry.status=="posted")&
                  (JournalEntry.entry_date>=start)&(JournalEntry.entry_date<=end))
       .filter(Account.is_group.is_(False)))
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

@bp.get("/trial-balance")
@permission_required("reports.view")
def trial_balance():
    start,end=parse_dates()
    rows=_account_period_rows(start,end)
    debit_total=sum((r["debit"] for r in rows),D(0))
    credit_total=sum((r["credit"] for r in rows),D(0))
    return render_template("reports/trial_balance.html",rows=rows,start=start,end=end,debit_total=debit_total,credit_total=credit_total)
