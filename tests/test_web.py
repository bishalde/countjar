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


def test_only_owner_manages_tokens_and_removal_revokes(client, ctx):
    from tests.conftest import make_user
    from countjar import tokens
    owner = make_user("+14155550199", "Owner")
    ws = accounts.create_workspace(owner, "team", "Team")
    login(client, workspace="mine")  # Grace, +14155550123
    grace = db.col("users").find_one({"phone": "+14155550123"})
    accounts.add_member(ws, grace["phone"])
    assert post(client, "/app/team/tokens", {"name": "x", "scopes": "admin"}).status_code == 403
    _, raw = tokens.create_token(ws, grace, "old", ["admin"])
    accounts.remove_member(ws, grace["_id"])
    assert tokens.authenticate(raw) is None


def test_token_name_is_escaped_in_revoke_prompt(signed_in):
    post(signed_in, "/app/mine/tokens", {"name": "');alert(1)//", "scopes": "read"})
    html = signed_in.get("/app/mine/tokens").get_data(as_text=True)
    import html as htmllib
    handler = htmllib.unescape(re.search(r'onsubmit="([^"]*)"', html).group(1))
    arg = re.fullmatch(r"return confirm\((.*)\)", handler).group(1)
    assert json.loads(arg).startswith("Revoke ');alert(1)//?")  # one string literal, nothing after it


def test_non_ascii_csrf_token_is_rejected_not_crash(signed_in):
    resp = signed_in.post("/app/mine/counters", data={"csrf_token": "é", "name": "x"})
    assert resp.status_code == 400


def test_history_export_bad_range_is_400(signed_in):
    post(signed_in, "/app/mine/counters", {"name": "dl"})
    assert signed_in.get("/app/mine/c/dl/export.csv?kind=history&range=5y").status_code == 400


def test_member_adds_are_rate_limited(signed_in, monkeypatch):
    from countjar import web
    monkeypatch.setattr(web, "MEMBER_ADDS_PER_HOUR", 2)
    for _ in range(2):
        post(signed_in, "/app/mine/members", {"phone": "+14155550999"})
    resp = post(signed_in, "/app/mine/members", {"phone": "+14155550999"}, follow_redirects=True)
    assert "a lot of people this hour" in resp.get_data(as_text=True)


def test_removed_member_stops_getting_texts(signed_in):
    from countjar import notify
    from tests.conftest import make_user
    ws = ws_doc()
    mate = make_user("+14155550188", "Mate")
    accounts.add_member(ws, mate["phone"])
    c = counters.create_counter(ws, "watched")
    notify.add_milestone(ws, c, 5, "sms", mate["phone"], user=mate)
    accounts.remove_member(ws_doc(), mate["_id"])
    assert db.col("milestones").count_documents({"target": mate["phone"]}) == 0


def test_footer_credits_developer_and_links(client):
    html = client.get("/").get_data(as_text=True)
    assert "Made with" in html and ">Bishal</a>" in html
    for href in ("https://github.com/bishalde/countjar", "https://www.linkedin.com/in/bishalde/",
                 "https://bishalde.vercel.app/"):
        assert f'href="{href}" target="_blank" rel="noopener noreferrer"' in html


def test_site_visit_counting_never_breaks_the_page(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(counters, "apply", boom)
    resp = client.get("/", headers={"User-Agent": "Mozilla/5.0 Firefox/130"})
    assert resp.status_code == 200


def test_failed_code_sends_do_not_use_up_attempts(app, client, monkeypatch):
    from countjar import verify

    def fail(phone):
        raise verify.VerifyError("Phone verification is not configured on this server.")
    monkeypatch.setattr(verify, "send_code", fail)
    with app.app_context():
        for _ in range(8):
            resp = post(client, "/login", {"country": "US", "phone": "4155550142"})
            assert "not configured" in resp.get_data(as_text=True)
            assert "Too many codes" not in resp.get_data(as_text=True)


def test_code_limit_says_how_long_to_wait(app, client):
    with app.app_context():
        for _ in range(5):
            post(client, "/login", {"country": "US", "phone": "4155550143"})
            client.get("/logout")
        with client.session_transaction() as s:
            s.pop("pending_phone", None)
        resp = post(client, "/login", {"country": "US", "phone": "4155550143"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 429
    assert re.search(r"Try again in (a minute|\d+ minutes)", body)
