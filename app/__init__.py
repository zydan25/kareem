from flask import Flask, render_template, request
from config import Config
from .extensions import db, migrate, login_manager
from .permissions import can

ROLE_LABELS = {
    "admin": "مدير النظام",
    "manager": "مدير",
    "accountant": "محاسب",
    "collector": "متحصل",
    "auditor": "مراجع",
}

def _read_setting(key, default):
    try:
        from .models import Setting
        row=db.session.query(Setting).filter_by(key=key).first()
        return row.value if row and row.value is not None else default
    except Exception:
        return default

def create_app(config_class=Config):
    app=Flask(__name__)
    app.config.from_object(config_class)
    db.init_app(app)
    migrate.init_app(app,db)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User,int(user_id))

    login_manager.init_app(app)

    from .blueprints.auth import bp as auth_bp
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.collector import bp as collector_bp
    from .blueprints.master_data import bp as master_data_bp
    from .blueprints.accounting import bp as accounting_bp
    from .blueprints.operations import bp as operations_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.reports import bp as reports_bp
    from .blueprints.settings import bp as settings_bp

    for blueprint in (auth_bp,dashboard_bp,collector_bp,master_data_bp,accounting_bp,operations_bp,
                      admin_bp,reports_bp,settings_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(403)
    def handle_forbidden(error):
        return render_template("errors/403.html", attempted_path=request.path), 403

    @app.after_request
    def disable_browser_cache(response):
        # HTML/API/manifests stay uncached so settings changes appear immediately.
        # Versioned static/branding assets may be cached safely because their
        # URLs change when the branding version changes.
        if request.path.startswith("/settings/brand/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers.pop("Pragma", None)
            response.headers.pop("Expires", None)
        else:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.context_processor
    def inject_globals():
        organization_name=_read_setting("organization_name",app.config["PWA_NAME"])
        project_name=_read_setting("project_name","إدارة السوق والمحاسبة")
        currency_name=_read_setting("currency_name",app.config["DEFAULT_CURRENCY"])
        brand_color=_read_setting("brand_color","#0b6e4f")
        if not isinstance(brand_color,str) or not __import__("re").fullmatch(r"#[0-9a-fA-F]{6}",brand_color):
            brand_color="#0b6e4f"
        login_theme=_read_setting("login_theme","emerald")
        if login_theme not in {"emerald","ocean","midnight","sand","minimal"}: login_theme="emerald"
        admin_theme=_read_setting("admin_theme","classic")
        if admin_theme not in {"classic","water","water_project"}: admin_theme="classic"
        rental_ui_theme=_read_setting("rental_ui_theme","mobile")
        if rental_ui_theme not in {"classic","mobile"}: rental_ui_theme="mobile"
        font_size=_read_setting("font_size","100")
        if font_size not in {"100","110","120","130"}: font_size="100"
        collector_font_size=_read_setting("collector_font_size","120")
        if collector_font_size not in {"100","110","120","130","140"}: collector_font_size="120"
        return {
            "app_name":organization_name or app.config["PWA_NAME"],
            "project_name":project_name or "إدارة السوق والمحاسبة",
            "currency":currency_name or app.config["DEFAULT_CURRENCY"],
            "brand_color":brand_color,
            "brand_logo":_read_setting("brand_logo",""),
            "brand_icon":_read_setting("brand_icon",""),
            "brand_icon_enabled":_read_setting("brand_icon_enabled","1") == "1",
            "brand_version":_read_setting("brand_version","1"),
            "login_theme":login_theme,
            "admin_theme":admin_theme,
            "rental_ui_theme":rental_ui_theme,
            "ui_font_scale":str(float(font_size)/100),
            "collector_font_scale":str(float(collector_font_size)/100),
            "can":can,
            "role_labels": ROLE_LABELS,
        }
    return app
