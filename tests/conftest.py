import pytest
from flask_migrate import upgrade
from app import create_app
from app.extensions import db
from app.services.setup import seed

class TestConfig:
    TESTING=True
    SECRET_KEY="test-secret"
    SQLALCHEMY_TRACK_MODIFICATIONS=False

@pytest.fixture()
def app(tmp_path):
    test_db=tmp_path/"kareem-test.sqlite"
    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{test_db}"
    app=create_app(Config)
    with app.app_context():
        upgrade()
        seed()
        yield app
        db.session.remove()

@pytest.fixture()
def client(app):
    return app.test_client()
