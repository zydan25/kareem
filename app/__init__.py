from flask import Flask
from config import Config
from .extensions import db, migrate, login_manager
from .permissions import can

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

    for blueprint in (auth_bp,dashboard_bp,collector_bp,master_data_bp,accounting_bp,
                      operations_bp,admin_bp,reports_bp,settings_bp):
        app.register_blueprint(blueprint)

    @app.context_processor
    def inject_globals():
        return {
            "app_name":app.config["PWA_NAME"],
            "currency":app.config["DEFAULT_CURRENCY"],
            "can":can,
        }
    return app
