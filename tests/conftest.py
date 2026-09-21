import pytest
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
        db.create_all(); seed()
        yield app
        db.session.remove(); db.drop_all()

@pytest.fixture()
def client(app):
    return app.test_client()
