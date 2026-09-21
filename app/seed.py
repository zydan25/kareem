from flask import Flask
from flask_migrate import upgrade

from app import create_app
from app.services.setup import seed

app: Flask = create_app()
with app.app_context():
    upgrade()
    seed()
    print("تم تطبيق ترحيلات قاعدة البيانات وتجهيز بيانات النظام.")
