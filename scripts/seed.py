from app import create_app
from app.services.setup import seed

app=create_app()
with app.app_context():
    seed()
    print("System data seeded.")
