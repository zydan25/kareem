import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.services.setup import seed

app=create_app()
with app.app_context():
    seed()
    print("System data seeded.")
