import pytest
from flask_migrate import upgrade, downgrade
from app import create_app
from app.extensions import db
from app.services.setup import seed

class TestConfig:
    TESTING=True
    SECRET_KEY="test-secret"
    SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS=False

@pytest.fixture()
def app():
    app=create_app(TestConfig)
    with app.app_context():
        upgrade()
        seed()
        yield app
        db.session.remove()

@pytest.fixture()
def client(app):
    return app.test_client()
