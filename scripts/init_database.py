from flask_migrate import upgrade
from app import create_app
from app.services.setup import seed

app=create_app()
with app.app_context():
    upgrade()
    seed()
    print("Database migrations applied and system data seeded.")
