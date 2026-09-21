from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_

from ..extensions import db
from ..models import User
from ..permissions import permission_required
from ..services.audit import audit

bp=Blueprint("auth",__name__)

@bp.route("/login",methods=["GET","POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method=="POST":
        identifier=request.form.get("identifier","").strip()
        password=request.form.get("password","")
        user=(User.query.filter(
            User.active.is_(True),
            or_(User.phone==identifier,User.username==identifier)
        ).first())
        if user and user.check_password(password):
            login_user(user,remember=request.form.get("remember")=="1")
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("رقم الهاتف/اسم المستخدم أو كلمة المرور غير صحيحة","danger")
    return render_template("auth/login.html")

@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

@bp.route("/account",methods=["GET","POST"])
@permission_required("dashboard.view")
def account():
    if request.method=="POST":
        try:
            full_name=request.form.get("full_name","").strip()
            phone=request.form.get("phone","").strip() or None
            new_password=request.form.get("new_password","")
            other=User.query.filter(User.phone==phone,User.id!=current_user.id).first() if phone else None
            if other:
                raise ValueError("رقم الهاتف مستخدم لحساب آخر")
            if not full_name:
                raise ValueError("الاسم مطلوب")
            current_user.full_name=full_name
            current_user.phone=phone
            if current_user.employee:
                current_user.employee.full_name=full_name
                current_user.employee.phone=phone
            if new_password:
                if len(new_password)<4:
                    raise ValueError("كلمة المرور الجديدة قصيرة جدًا")
                current_user.set_password(new_password)
            audit("update","user",current_user.id,current_user.username)
            db.session.commit()
            flash("تم تحديث حسابك بنجاح","success")
            return redirect(url_for("auth.account"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc),"danger")
    return render_template("auth/account.html",user=current_user)
