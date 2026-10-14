import mongomock
import pytest

from countjar import accounts, counters, create_app, db, tokens, verify


@pytest.fixture
def app():
    db.set_client(mongomock.MongoClient(tz_aware=True))
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "MONGODB_URI": None,
        "VERIFY_DEV_MODE": True,
        "ON_VERCEL": False,
        "SITE_URL": "https://countjar.test",
    })
    with app.app_context():
        db.init()
    verify._dev_codes.clear()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ctx(app):
    with app.test_request_context():
        yield


def make_user(phone="+14155550100", name="Ada"):
    u = accounts.get_or_create_user(phone)
    accounts.update_profile(u, name)
    return db.col("users").find_one({"_id": u["_id"]})


@pytest.fixture
def owner(ctx):
    return make_user()


@pytest.fixture
def ws(owner):
    return accounts.create_workspace(owner, "acme", "Acme")


@pytest.fixture
def counter(ws):
    return counters.create_counter(ws, "visits")


@pytest.fixture
def token_factory(ws, owner):
    def make(*scopes):
        return tokens.create_token(ws, owner, "t", list(scopes))[1]
    return make


def csrf(client):
    client.get("/login")  # any page that renders csrf_token()
    with client.session_transaction() as s:
        if "csrf" not in s:
            s["csrf"] = "tok"
        return s["csrf"]


def post(client, url, data=None, **kw):
    data = dict(data or {})
    data["csrf_token"] = csrf(client)
    return client.post(url, data=data, **kw)


def login(client, phone="+14155550123", name="Grace", workspace="grace"):
    post(client, "/login", {"country": "US", "phone": phone})
    code = verify._dev_codes[phone]
    resp = post(client, "/login/verify", {"code": code})
    if "/onboarding" in resp.headers.get("Location", ""):
        post(client, "/onboarding", {"name": name, "workspace": workspace})
    return resp
