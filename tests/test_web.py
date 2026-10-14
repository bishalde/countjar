import json
import re

import pytest

from countjar import accounts, counters, db
from tests.conftest import login, post


@pytest.fixture
def signed_in(app, client):
    with app.app_context():
        login(client, workspace="mine")
        yield client


def ws_doc(slug="mine"):
    return db.col("workspaces").find_one({"slug": slug})


# --- public site -------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/pricing", "/login", "/solutions/counter-api",
                                  "/solutions/website-hit-counter", "/solutions/poll-widget"])
def test_public_pages_render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "<title>" in resp.get_data(as_text=True)


def test_unknown_solution_is_404(client):
    resp = client.get("/solutions/nope")
    assert resp.status_code == 404
    assert "text/html" in resp.content_type


def test_landing_has_canonical_and_jsonld(client):
    html = client.get("/").get_data(as_text=True)
    assert '<link rel="canonical" href="https://countjar.test/"' in html
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert blocks
    kinds = set()
    for b in blocks:
        data = json.loads(b)
        for item in data.get("@graph", [data]):
            kinds.add(item["@type"])
    assert {"SoftwareApplication", "FAQPage"} <= kinds


def test_solution_page_jsonld_is_valid(client):
    html = client.get("/solutions/counter-api").get_data(as_text=True)
    for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        json.loads(b)


def test_robots_and_sitemap(client):
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /app/" in robots and "Disallow: /api/" in robots
    assert "Sitemap: https://countjar.test/sitemap.xml" in robots
    sitemap = client.get("/sitemap.xml")
    assert sitemap.content_type.startswith("application/xml")
    body = sitemap.get_data(as_text=True)
    assert "https://countjar.test/solutions/counter-api" in body
    assert "/app/" not in body


def test_old_jar_url_redirects(client):
    resp = client.get("/jar/anything")
    assert resp.status_code == 301


# --- auth ---------------------------------------------------------------------

def test_dashboard_requires_login(client):
    resp = client.get("/app/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_post_without_csrf_is_rejected(signed_in):
    resp = signed_in.post("/app/mine/counters", data={"name": "x"})
    assert resp.status_code == 400
    assert counters.list_counters(ws_doc()) == []


def test_wrong_otp_shows_error(client):
    post(client, "/login", {"country": "US", "phone": "4155550123"})
    resp = post(client, "/login/verify", {"code": "000000"})
    assert resp.status_code in (200, 400)
    assert client.get("/app/").status_code == 302


def test_invalid_phone_is_rejected(client):
    resp = post(client, "/login", {"country": "US", "phone": "12"})
    assert resp.status_code in (200, 400)
    assert "/login/verify" not in resp.headers.get("Location", "")


def test_logout_clears_session(signed_in):
    post(signed_in, "/logout")
    assert signed_in.get("/app/").status_code == 302


# --- dashboard ----------------------------------------------------------------

def test_dashboard_pages_render_with_noindex(signed_in):
    ws = ws_doc()
    for kind in ("count", "like", "poll", "rating"):
        counters.create_counter(ws, f"c-{kind}", type=kind)
    paths = ["/app/", "/app/mine", "/app/mine/counters", "/app/mine/counters?new=1",
             "/app/mine/tokens", "/app/mine/members", "/app/mine/settings", "/app/account",
             "/app/mine/history.json"]
    for kind in ("count", "like", "poll", "rating"):
        for tab in ("overview", "embed", "milestones", "events", "settings"):
            paths.append(f"/app/mine/c/c-{kind}?tab={tab}")
        paths.append(f"/app/mine/c/c-{kind}/history.json?range=7d")
        paths.append(f"/app/mine/c/c-{kind}/export.csv")
    for path in paths:
        resp = signed_in.get(path, follow_redirects=True)
        assert resp.status_code == 200, path
        assert "noindex" in resp.headers.get("X-Robots-Tag", ""), path


def test_create_counter_through_form_and_budget(signed_in):
    for i in range(5):
        resp = post(signed_in, "/app/mine/counters", {"name": f"n{i}", "type": "count"})
        assert resp.status_code == 302
        assert f"/app/mine/c/n{i}" in resp.headers["Location"]
    resp = post(signed_in, "/app/mine/counters", {"name": "n5", "type": "count"},
                follow_redirects=True)
    assert "all 5 counters" in resp.get_data(as_text=True)
    assert len(counters.list_counters(ws_doc())) == 5


def test_counter_action_json(signed_in):
    counters.create_counter(ws_doc(), "hits")
    resp = post(signed_in, "/app/mine/c/hits/action", {"action": "up"},
                headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1


def test_delete_counter_needs_name(signed_in):
    counters.create_counter(ws_doc(), "hits")
    post(signed_in, "/app/mine/c/hits/delete", {"confirm": "wrong"})
    assert counters.find("mine", "hits")[1] is not None
    post(signed_in, "/app/mine/c/hits/delete", {"confirm": "hits"})
    assert counters.find("mine", "hits")[1] is None


def test_token_shown_once(signed_in):
    resp = post(signed_in, "/app/mine/tokens", {"name": "ci", "scopes": "write"})
    html = resp.get_data(as_text=True)
    assert re.search(r"cj_[A-Za-z0-9_-]{20,}", html)
    again = signed_in.get("/app/mine/tokens").get_data(as_text=True)
    assert not re.search(r"cj_[A-Za-z0-9_-]{20,}", again)


def test_non_member_gets_404(client, ctx):
    from tests.conftest import make_user
    other = make_user("+14155550199", "Other")
    ws = accounts.create_workspace(other, "theirs", "Theirs")
    counters.create_counter(ws, "secret")
    login(client, workspace="mine")
    assert client.get("/app/theirs").status_code == 404
    assert client.get("/app/theirs/c/secret").status_code == 404
    assert post(client, "/app/theirs/c/secret/delete", {"confirm": "secret"}).status_code == 404


def test_demo_workspace_not_in_dashboard(signed_in):
    assert signed_in.get("/app/demo").status_code == 404


def test_alpine_attributes_survive_json_quotes(client):
    html = client.get("/").get_data(as_text=True)
    m = re.search(r'x-data="(demoJar\([^"]*)"', html)
    assert m and m.group(1).endswith(")")


# --- site visitor counter -----------------------------------------------------

def site_visitors():
    ws = db.col("workspaces").find_one({"slug": "demo"})
    return db.col("counters").find_one({"workspace_id": ws["_id"], "name": "site-visitors"})["count"]


def test_public_pages_count_each_visitor_once_a_day(client):
    client.get("/", headers={"User-Agent": "Mozilla/5.0 A"})
    client.get("/pricing", headers={"User-Agent": "Mozilla/5.0 A"})
    client.get("/", headers={"User-Agent": "Mozilla/5.0 B"})
    assert site_visitors() == 2


def test_bots_and_machine_files_are_not_counted(client):
    client.get("/", headers={"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"})
    client.get("/robots.txt", headers={"User-Agent": "Mozilla/5.0 A"})
    client.get("/sitemap.xml", headers={"User-Agent": "Mozilla/5.0 A"})
    client.head("/", headers={"User-Agent": "Mozilla/5.0 A"})
    assert site_visitors() == 0


def test_footer_shows_visitor_count(client):
    html = client.get("/", headers={"User-Agent": "Mozilla/5.0 A"}).get_data(as_text=True)
    assert re.search(r">1</span> visitor,", html)


@pytest.mark.parametrize("path", ["/api/v2/demo/site-visitors", "/api/v2/demo/site-visitors/up",
                                  "/api/v2/demo/site-visitors/down", "/api/v2/demo/site-visitors/reset"])
def test_site_visitor_counter_is_not_reachable_through_api(client, path):
    assert client.get(path).status_code == 401
    assert site_visitors() == 0


def test_demo_summary_hides_site_visitor_counter(client):
    names = [c["name"] for c in client.get("/api/v2/demo").get_json()["counters"]]
    assert "site-visitors" not in names
