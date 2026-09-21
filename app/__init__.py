from flask import Flask
from config import Config
from .extensions import db, migrate, login_manager

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .blueprints.auth import bp as auth_bp
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.collector import bp as collector_bp
    from .blueprints.master_data import bp as master_data_bp
    from .blueprints.accounting import bp as accounting_bp
    from .blueprints.reports import bp as reports_bp
    from .blueprints.settings import bp as settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(collector_bp)
    app.register_blueprint(master_data_bp)
    app.register_blueprint(accounting_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)

    @app.context_processor
    def inject_globals():
        return {"app_name": app.config["PWA_NAME"], "currency": app.config["DEFAULT_CURRENCY"]}

    return app
