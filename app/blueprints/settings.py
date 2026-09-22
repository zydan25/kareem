import re
import time
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from ..extensions import db
from ..models import Setting, VehicleType
from ..permissions import can, permission_required
from ..services.audit import audit

bp=Blueprint("settings",__name__,url_prefix="/settings")
ALLOWED_IMAGE_EXTENSIONS={"png","jpg","jpeg","webp"}
BUILTIN_ICON="__builtin__:souq-aljumla.svg"

def _setting(key, default=""):
    row=Setting.query.filter_by(key=key).first()
    return row.value if row and row.value is not None else default

def _save_setting(key, value, value_type="string", description=None):
    row=Setting.query.filter_by(key=key).first()
    if not row:
        row=Setting(key=key,value=value,value_type=value_type,description=description)
        db.session.add(row)
    else:
        row.value=value
        row.value_type=value_type
        if description and not row.description:
            row.description=description
    return row

def _save_brand_image(file_storage, key_prefix):
    if not file_storage or not file_storage.filename:
        return
    ext=Path(file_storage.filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("الشعار والأيقونة: PNG أو JPG أو WEBP فقط")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ValueError("ضغط الصور غير متاح حاليًا؛ ثبّت Pillow من المتطلبات أولًا") from exc

    file_storage.stream.seek(0, 2)
    size=file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > 5 * 1024 * 1024:
        raise ValueError("الصورة كبيرة جدًا؛ الحد الأقصى 5 ميجابايت")
    try:
        image=Image.open(file_storage.stream)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("الملف المرفوع ليس صورة صالحة") from exc

    image=image.convert("RGBA")
    max_side=256 if key_prefix=="brand_icon" else 1400
    image.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)

    folder=Path(current_app.config["UPLOAD_FOLDER"])/"site_brand"
    folder.mkdir(parents=True,exist_ok=True)
    old=_setting(key_prefix,"")
    if old:
        old_path=folder/old
        if old_path.exists():
            try:
                old_path.unlink()
            except OSError:
                pass

    filename=f"{key_prefix}-{int(time.time())}-{int(time.time_ns()) % 1000000}.png"
    image.save(folder/filename,format="PNG",optimize=True)
    _save_setting(key_prefix,filename,"string",key_prefix)

@bp.route("",methods=["GET","POST"])
@permission_required("settings.view")
def index():
    types=VehicleType.query.order_by(VehicleType.active.desc(),VehicleType.name).all()
    if request.method=="POST":
        if not can("settings.manage"):
            return ("Forbidden",403)
        try:
            vehicle_type_name=request.form.get("vehicle_type_name","").strip()
            organization_name=request.form.get("setting_organization_name","").strip() or "سوق الجملة"
            project_name=request.form.get("setting_project_name","").strip() or "إدارة السوق والمحاسبة"
            currency_name=request.form.get("setting_currency_name","").strip() or "ريال يمني"
            brand_color=request.form.get("setting_brand_color","#0b6e4f").strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}",brand_color):
                brand_color="#0b6e4f"
            _save_setting("organization_name",organization_name,"string","اسم المنشأة")
            _save_setting("project_name",project_name,"string","الوصف تحت الاسم")
            _save_setting("currency_name",currency_name,"string","العملة")
            _save_setting("brand_color",brand_color,"string","اللون الرئيسي")
            _save_setting("ui_theme",request.form.get("setting_ui_theme","light"),"string","المظهر")
            _save_setting("customer_portal",request.form.get("setting_customer_portal","0"),"boolean","إتاحة لوحة العميل")
            _save_brand_image(request.files.get("brand_logo"),"brand_logo")
            _save_brand_image(request.files.get("brand_icon"),"brand_icon")
            _save_setting("brand_version",str(int(time.time())),"string","نسخة الهوية")

            if vehicle_type_name and not VehicleType.query.filter_by(name=vehicle_type_name).first():
                row=VehicleType(name=vehicle_type_name,is_system=False,active=True)
                db.session.add(row)
                db.session.flush()
                audit("create","vehicle_type",row.id,row.name)

            db.session.commit()
            flash("تم حفظ إعدادات الهوية والموقع","success")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc),"danger")

    return render_template(
        "settings/index.html",
        vehicle_types=types,
        can_manage=can("settings.manage"),
        settings=Setting.query.order_by(Setting.key).all(),
        brand_color=_setting("brand_color","#0b6e4f"),
        brand_logo=_setting("brand_logo",""),
        brand_icon=_setting("brand_icon",""),
        brand_version=_setting("brand_version","1"),
        organization_name=_setting("organization_name","سوق الجملة"),
        project_name=_setting("project_name","إدارة السوق والمحاسبة"),
        currency_name=_setting("currency_name","ريال يمني"),
    )

@bp.get("/brand/<kind>")
def brand_asset(kind):
    if kind not in {"logo","icon"}:
        abort(404)
    filename=_setting("brand_"+kind,"")
    if not filename:
        return redirect(url_for("static",filename="icons/icon.svg"))
    if kind=="icon" and filename==BUILTIN_ICON:
        response=send_file(Path(current_app.static_folder)/"icons"/"souq-aljumla.svg",mimetype="image/svg+xml",max_age=3600)
        response.headers["Cache-Control"]="public, max-age=3600, immutable"
        return response
    path=Path(current_app.config["UPLOAD_FOLDER"])/"site_brand"/filename
    if not path.exists():
        return redirect(url_for("static",filename="icons/icon.svg"))
    response=send_file(path,max_age=0)
    response.headers["Cache-Control"]="no-cache, no-store, must-revalidate"
    return response

@bp.get("/manifest.webmanifest")
def manifest():
    name=_setting("organization_name",current_app.config["PWA_NAME"])
    description=_setting("project_name","إدارة السوق والمحاسبة")
    color=_setting("brand_color","#0b6e4f")
    icon_url=url_for("settings.brand_asset",kind="icon",_external=True)
    icon_filename=_setting("brand_icon","")
    icon_type="image/svg+xml" if not icon_filename or icon_filename==BUILTIN_ICON else "image/png"
    return jsonify({
        "name":name,
        "short_name":(name[:18] or current_app.config["PWA_SHORT_NAME"]),
        "description":description,
        "start_url":"/dashboard",
        "display":"standalone",
        "background_color":"#f4f7f6",
        "theme_color":color,
        "dir":"rtl",
        "lang":"ar",
        "icons":[{"src":icon_url,"sizes":"any","type":icon_type,"purpose":"any maskable"}]
    })

@bp.post("/brand/icon/use-default")
@permission_required("settings.manage")
def use_default_brand_icon():
    old=_setting("brand_icon","")
    if old and not old.startswith("__builtin__:"):
        path=Path(current_app.config["UPLOAD_FOLDER"])/"site_brand"/old
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    _save_setting("brand_icon",BUILTIN_ICON,"string","الأيقونة المقترحة")
    _save_setting("brand_version",str(int(time.time())),"string","نسخة الهوية")
    db.session.commit()
    flash("تم اعتماد أيقونة «سوق الجملة»","success")
    return redirect(url_for("settings.index"))

@bp.post("/brand/icon/reset")
@permission_required("settings.manage")
def reset_brand_icon():
    old=_setting("brand_icon","")
    if old and old!=BUILTIN_ICON:
        path=Path(current_app.config["UPLOAD_FOLDER"])/"site_brand"/old
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    _save_setting("brand_icon","")
    _save_setting("brand_version",str(int(time.time())),"string","نسخة الهوية")
    db.session.commit()
    flash("تمت استعادة الأيقونة التقليدية للنظام","success")
    return redirect(url_for("settings.index"))

@bp.post("/vehicle-types/<int:type_id>/toggle")
@permission_required("settings.manage")
def toggle_type(type_id):
    row=db.session.get(VehicleType,type_id)
    if row.is_system:
        flash("لا يمكن تعطيل نوع نظامي","warning")
    else:
        row.active=not row.active
        audit("toggle","vehicle_type",row.id,row.name)
        db.session.commit()
    return redirect(url_for("settings.index"))
