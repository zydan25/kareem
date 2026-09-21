from datetime import datetime, date
from decimal import Decimal
from enum import Enum

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint, Index
from sqlalchemy.orm import validates
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db

class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class Role(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    ACCOUNTANT = "accountant"
    COLLECTOR = "collector"
    AUDITOR = "auditor"

class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default=Role.COLLECTOR.value, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="SET NULL"))

    def set_password(self, value):
        self.password_hash = generate_password_hash(value)
    def check_password(self, value):
        return check_password_hash(self.password_hash, value)
    def has_role(self, *roles):
        values = {r.value if isinstance(r, Role) else r for r in roles}
        return self.role in values

class Employee(TimestampMixin, db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30))
    job_title = db.Column(db.String(100), default="موظف")
    monthly_salary = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hire_date = db.Column(db.Date, default=date.today)
    active = db.Column(db.Boolean, nullable=False, default=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="SET NULL"), unique=True)
    user = db.relationship("User", backref="employee_record", uselist=False, foreign_keys=[User.employee_id])
    account = db.relationship("Account", foreign_keys=[account_id])

class Agent(TimestampMixin, db.Model):
    __tablename__ = "agents"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="SET NULL"), unique=True)
    account = db.relationship("Account", foreign_keys=[account_id])

class Client(TimestampMixin, db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(30))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="SET NULL"), unique=True)
    account = db.relationship("Account", foreign_keys=[account_id])

class ClientAgent(TimestampMixin, db.Model):
    __tablename__ = "client_agents"
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    priority = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("client_id", "agent_id", name="uq_client_agent"),)

class VehicleType(TimestampMixin, db.Model):
    __tablename__ = "vehicle_types"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    is_system = db.Column(db.Boolean, nullable=False, default=False)

class Vehicle(TimestampMixin, db.Model):
    __tablename__ = "vehicles"
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(40), nullable=False)
    plate_separator = db.Column(db.String(40))
    plate_letters = db.Column(db.String(40))
    vehicle_type_id = db.Column(db.Integer, db.ForeignKey("vehicle_types.id", ondelete="RESTRICT"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"))
    vehicle_type = db.relationship("VehicleType")
    client = db.relationship("Client")
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint("plate_number", "plate_separator", name="uq_vehicle_plate"),
        Index("ix_vehicle_plate_search", "plate_number", "plate_separator"),
    )

class VehicleAgent(TimestampMixin, db.Model):
    __tablename__ = "vehicle_agents"
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    last_used_at = db.Column(db.DateTime(timezone=True))
    active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("vehicle_id", "agent_id", name="uq_vehicle_agent"),)

class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"
    MEMO = "memo"

class Account(TimestampMixin, db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    name = db.Column(db.String(180), nullable=False)
    account_type = db.Column(db.String(30), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="RESTRICT"))
    is_group = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    allow_manual_posting = db.Column(db.Boolean, nullable=False, default=True)
    system_key = db.Column(db.String(80), unique=True)
    parent = db.relationship("Account", remote_side=[id], backref="children")
    __table_args__ = (CheckConstraint("NOT (is_group = TRUE AND allow_manual_posting = TRUE)", name="ck_group_not_postable"),)

    @validates("account_type")
    def validate_type(self, key, value):
        allowed = {x.value for x in AccountType}
        if value not in allowed:
            raise ValueError(f"نوع حساب غير صالح: {value}")
        return value

class EntryStatus(str, Enum):
    DRAFT = "draft"
    POSTED = "posted"
    VOID = "void"

class JournalEntry(TimestampMixin, db.Model):
    __tablename__ = "journal_entries"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    entry_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    description = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=EntryStatus.DRAFT.value)
    source_type = db.Column(db.String(50), nullable=False, default="manual")
    source_id = db.Column(db.Integer)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    posted_at = db.Column(db.DateTime(timezone=True))
    reversed_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="SET NULL"))
    lines = db.relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan", order_by="JournalLine.id")
    __table_args__ = (CheckConstraint("status IN ('draft','posted','void')", name="ck_journal_status"),)

    def totals(self):
        debit = sum((line.debit or Decimal("0") for line in self.lines), Decimal("0"))
        credit = sum((line.credit or Decimal("0") for line in self.lines), Decimal("0"))
        return debit, credit

class JournalLine(db.Model):
    __tablename__ = "journal_lines"
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    description = db.Column(db.String(500))
    debit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    credit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reference = db.Column(db.String(100))
    entry = db.relationship("JournalEntry", back_populates="lines")
    account = db.relationship("Account")
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_line_non_negative"),
        CheckConstraint("(debit = 0) <> (credit = 0)", name="ck_line_one_side"),
    )

class VoucherType(str, Enum):
    RECEIPT = "receipt"
    PAYMENT = "payment"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"

class Voucher(TimestampMixin, db.Model):
    __tablename__ = "vouchers"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    voucher_type = db.Column(db.String(30), nullable=False)
    voucher_date = db.Column(db.Date, nullable=False, default=date.today)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    from_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="RESTRICT"))
    to_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id", ondelete="RESTRICT"))
    beneficiary = db.Column(db.String(180))
    description = db.Column(db.String(500))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="RESTRICT"))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

class Shift(TimestampMixin, db.Model):
    __tablename__ = "shifts"
    id = db.Column(db.Integer, primary_key=True)
    collector_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    shift_name = db.Column(db.String(50), nullable=False, default="وردية")
    opened_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime(timezone=True))
    opening_balance = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    closing_balance = db.Column(db.Numeric(18, 2))
    settlement_journal_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="SET NULL"))
    status = db.Column(db.String(20), nullable=False, default="open")

class GateTransaction(TimestampMixin, db.Model):
    __tablename__ = "gate_transactions"
    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    transaction_date = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)
    direction = db.Column(db.String(10), nullable=False, default="entry")
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"))
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id", ondelete="SET NULL"))
    collector_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    shift_id = db.Column(db.Integer, db.ForeignKey("shifts.id", ondelete="RESTRICT"))
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, default="cash")
    notes = db.Column(db.String(500))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="RESTRICT"))
    counted_for_work = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_gate_amount_nonnegative"),
        Index("ix_gate_collector_date", "collector_id", "transaction_date"),
    )

class AgentLease(TimestampMixin, db.Model):
    __tablename__ = "agent_leases"
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    name = db.Column(db.String(120), nullable=False, default="إيجار")
    monthly_amount = db.Column(db.Numeric(18, 2), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date)
    due_day = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)

class AgentRent(TimestampMixin, db.Model):
    __tablename__ = "agent_rents"
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    lease_id = db.Column(db.Integer, db.ForeignKey("agent_leases.id", ondelete="RESTRICT"), nullable=False)
    rent_month = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="unpaid")
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="SET NULL"))
    __table_args__ = (UniqueConstraint("agent_id", "rent_month", name="uq_agent_rent_month"),)

class PayrollRun(TimestampMixin, db.Model):
    __tablename__ = "payroll_runs"
    id = db.Column(db.Integer, primary_key=True)
    payroll_month = db.Column(db.Date, nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id", ondelete="SET NULL"))

class PayrollLine(db.Model):
    __tablename__ = "payroll_lines"
    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False)
    gross_amount = db.Column(db.Numeric(18, 2), nullable=False)
    deductions = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    net_amount = db.Column(db.Numeric(18, 2), nullable=False)

class Setting(TimestampMixin, db.Model):
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.Text)
    value_type = db.Column(db.String(30), nullable=False, default="string")
    description = db.Column(db.String(255))
