from app.models import Account,VehicleType
from app.extensions import db

def login(client):
    return client.post("/login",data={"username":"admin","password":"admin"},follow_redirects=True)

def test_seed_and_dashboard(client):
    response=login(client)
    assert response.status_code==200
    assert "سوق الجملة" in response.get_data(as_text=True)

def test_system_account_tree(app):
    with app.app_context():
        assert db.session.query(Account).filter(Account.is_group.is_(True)).count()==5
        assert db.session.query(VehicleType).count()>=7

def test_login_bad_password(client):
    response=client.post("/login",data={"username":"admin","password":"wrong"},follow_redirects=True)
    assert "بيانات الدخول غير صحيحة" in response.get_data(as_text=True)
