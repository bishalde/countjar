import pytest

from countjar import counters


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_public_read_and_up_without_token(client, counter):
    r = client.get("/api/v2/acme/visits/up")
    assert r.status_code == 200 and r.json["count"] == 1 and r.json["counted"] is True
    assert r.headers["Access-Control-Allow-Origin"] == "*"
    assert r.headers["X-RateLimit-Limit"] == "600"
    assert client.get("/api/v2/acme/visits").json["count"] == 1


def test_anonymous_cannot_down_set_reset(client, counter):
    client.get("/api/v2/acme/visits/up")
    for path in ("down", "set?value=9", "reset"):
        r = client.get(f"/api/v2/acme/visits/{path}")
        assert r.status_code == 401, path
        assert r.json["error"]["code"] == "unauthorized"
    assert client.get("/api/v2/acme/visits").json["count"] == 1


def test_anonymous_custom_step_rejected(client, counter):
    r = client.get("/api/v2/acme/visits/up?by=1000")
    assert r.status_code == 401
    assert client.get("/api/v2/acme/visits").json["count"] == 0


def test_write_token_can_do_everything(client, counter, token_factory):
    tok = token_factory("write")
    assert client.post("/api/v2/acme/visits/up?by=10", headers=auth(tok)).json["count"] == 10
    assert client.get("/api/v2/acme/visits/down", headers=auth(tok)).json["count"] == 9
    assert client.get(f"/api/v2/acme/visits/set?value=50&token={tok}").json["count"] == 50
    assert client.get("/api/v2/acme/visits/reset", headers=auth(tok)).json["count"] == 0


def test_read_token_cannot_write(client, counter, token_factory):
    r = client.get("/api/v2/acme/visits/down", headers=auth(token_factory("read")))
    assert r.status_code == 403


def test_private_counter_needs_token(client, ws, token_factory):
    counters.create_counter(ws, "secret", visibility="private")
    assert client.get("/api/v2/acme/secret").status_code == 401
    assert client.get("/api/v2/acme/secret/up").status_code == 401
    tok = token_factory("read")
    assert client.get("/api/v2/acme/secret", headers=auth(tok)).status_code == 200
    assert client.get("/api/v2/acme/secret/up", headers=auth(tok)).status_code == 403


def test_invalid_and_foreign_tokens(client, counter, ctx):
    assert client.get("/api/v2/acme/visits", headers=auth("cj_nope")).status_code == 401
    from countjar import accounts, tokens
    from tests.conftest import make_user
    other = make_user("+14155550999", "Eve")
    ows = accounts.create_workspace(other, "evil")
    _, raw = tokens.create_token(ows, other, "x", ["admin"])
    r = client.get("/api/v2/acme/visits/reset", headers=auth(raw))
    assert r.status_code == 403 and r.json["error"]["code"] == "wrong_workspace"


def test_not_found(client, ws):
    assert client.get("/api/v2/nope/x").json["error"]["code"] == "not_found"
    assert client.get("/api/v2/acme/missing").status_code == 404
    assert client.get("/api/v2/acme/missing/bogus").status_code == 404


def test_demo_counter_up_and_down_open(client):
    assert client.get("/api/v2/demo/test-counter/up").json["count"] == 1
    assert client.get("/api/v2/demo/test-counter/down").json["count"] == 0
    assert client.get("/api/v2/demo/test-counter/reset").status_code == 401


def test_rate_limit(app, client, counter):
    app.config["RATE_LIMIT"] = 2
    client.get("/api/v2/acme/visits")
    client.get("/api/v2/acme/visits")
    r = client.get("/api/v2/acme/visits")
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert r.headers["X-RateLimit-Remaining"] == "0"


def test_window_stats_history_events(client, counter, token_factory):
    client.get("/api/v2/acme/visits/up?ref=newsletter")
    r = client.get("/api/v2/acme/visits?window=24h").json
    assert r["window"]["count"] == 1 and r["window"]["unique"] == 1
    assert client.get("/api/v2/acme/visits?window=nope").status_code == 400
    s = client.get("/api/v2/acme/visits/stats").json
    assert s["total_ups"] == 1 and s["last_24h"] == 1
    h = client.get("/api/v2/acme/visits/history?range=24h").json
    assert len(h["series"]) == 24 and sum(p["ups"] for p in h["series"]) == 1
    csv = client.get("/api/v2/acme/visits/history?range=7d&format=csv")
    assert csv.headers["Content-Type"].startswith("text/csv")
    assert client.get("/api/v2/acme/visits/events").status_code == 401
    ev = client.get("/api/v2/acme/visits/events", headers=auth(token_factory("read"))).json
    assert ev["events"][0]["props"] == {"ref": "newsletter"}


def test_widget_actions(client, ws):
    counters.create_counter(ws, "poll", type="poll")
    counters.create_counter(ws, "stars", type="rating")
    counters.create_counter(ws, "likes", type="like")
    assert client.get("/api/v2/acme/poll/vote?choice=yes").json["yes_pct"] == 100
    assert client.get("/api/v2/acme/stars/rate?value=4").json["average"] == 4
    assert client.get("/api/v2/acme/likes/like").json["counted"] is True
    assert client.get("/api/v2/acme/likes/like").json["counted"] is False
    assert client.get("/api/v2/acme/poll/up").status_code == 400


def test_admin_crud_and_budget(client, ws, token_factory):
    tok = token_factory("admin")
    assert client.post("/api/v2/acme/counters", json={"name": "x"}).status_code == 401
    assert client.post("/api/v2/acme/counters", json={"name": "x"},
                       headers=auth(token_factory("write"))).status_code == 403
    for i in range(5):
        r = client.post("/api/v2/acme/counters", json={"name": f"c{i}", "start": 7},
                        headers=auth(tok))
        assert r.status_code == 201 and r.json["count"] == 7
    r = client.post("/api/v2/acme/counters", json={"name": "c6"}, headers=auth(tok))
    assert r.status_code == 403 and r.json["error"]["code"] == "counter_limit"
    r = client.patch("/api/v2/acme/c0", json={"visibility": "private"}, headers=auth(tok))
    assert r.json["visibility"] == "private"
    assert client.delete("/api/v2/acme/c0", headers=auth(tok)).status_code == 204
    assert client.post("/api/v2/acme/counters", json={"name": "c6"},
                       headers=auth(tok)).status_code == 201


def test_workspace_summary_hides_private(client, ws, token_factory):
    counters.create_counter(ws, "pub")
    counters.create_counter(ws, "priv", visibility="private")
    names = [c["name"] for c in client.get("/api/v2/acme").json["counters"]]
    assert names == ["pub"]
    r = client.get("/api/v2/acme", headers=auth(token_factory("read"))).json
    assert {c["name"] for c in r["counters"]} == {"pub", "priv"}


def test_session_cookie_is_not_api_auth(client, ctx):
    from tests.conftest import login
    login(client, workspace="mine")
    from countjar import accounts
    ws = accounts.get_workspace("mine")
    counters.create_counter(ws, "p", visibility="private")
    assert client.get("/api/v2/mine/p").status_code == 401


@pytest.mark.parametrize("body", ["[1, 2]", '"name"', "5"])
def test_non_object_json_body_is_400(client, ws, token_factory, body):
    tok = token_factory("admin")
    r = client.post("/api/v2/acme/counters", data=body, content_type="application/json",
                    headers=auth(tok))
    assert r.status_code == 400 and r.json["error"]["code"] == "invalid_body"
    counters.create_counter(ws, "p")
    r = client.patch("/api/v2/acme/p", data=body, content_type="application/json", headers=auth(tok))
    assert r.status_code == 400


def test_non_object_json_params_are_ignored(client, counter):
    r = client.post("/api/v2/acme/visits/up", data="[1]", content_type="application/json")
    assert r.status_code == 200 and r.json["count"] == 1


def test_counter_budget_holds_when_requests_race(app, ws):
    # Simulate a racing request that slipped past the budget check.
    for i in range(app.config["COUNTER_LIMIT"]):
        counters.create_counter(ws, f"r{i}")
    from unittest import mock
    from countjar import accounts
    with mock.patch.object(accounts, "budget", return_value={"used": 0, "limit": 5, "left": 5}):
        with pytest.raises(counters.CounterError):
            counters.create_counter(ws, "extra")
    assert accounts.owned_counter_count(ws["owner_id"]) == app.config["COUNTER_LIMIT"]
