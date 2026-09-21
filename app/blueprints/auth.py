from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user
from ..models import User
from ..extensions import db

bp=Blueprint("auth",__name__)

@bp.route("/login",methods=["GET","POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("dashboard.index"))
    if request.method=="POST":
        username=request.form.get("username","").strip(); password=request.form.get("password","")
        user=db.session.query(User).filter_by(username=username,active=True).first()
        if user and user.check_password(password):
            login_user(user,remember=True)
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("بيانات الدخول غير صحيحة","danger")
    return render_template("auth/login.html")

@bp.post("/logout")
def logout():
    logout_user(); return redirect(url_for("auth.login"))
