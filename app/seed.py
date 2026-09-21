from app import create_app
from app.extensions import db
from app.services.setup import seed

app=create_app()
with app.app_context():
    db.create_all()
    seed()
    print("تم تجهيز قاعدة سوق الجملة والحسابات النظامية.")
    print("الحساب: admin | كلمة المرور: admin")
