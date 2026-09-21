from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from flask import current_app
from app import create_app
from app.extensions import db

config=context.config
if config.config_file_name is not None and config.has_section("loggers"):
    fileConfig(config.config_file_name)

try:
    app=current_app._get_current_object()
except RuntimeError:
    app=create_app()

with app.app_context():
    target_metadata=db.metadata

def run_migrations_offline():
    context.configure(url=app.config["SQLALCHEMY_DATABASE_URI"],target_metadata=target_metadata,
                      literal_binds=True,dialect_opts={"paramstyle":"named"},compare_type=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    section=config.get_section(config.config_ini_section,{}) or {}
    section["sqlalchemy.url"]=app.config["SQLALCHEMY_DATABASE_URI"]
    connectable=engine_from_config(section,prefix="sqlalchemy.",poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
