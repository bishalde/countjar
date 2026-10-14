import socket
from unittest import mock

import pytest

from countjar import accounts, counters, db, notify, ratelimit, stats, tokens
from tests.conftest import make_user


# ---------- embeds ----------

def test_badge_increments_and_renders(client, counter):
    r = client.get("/badge/acme/visits.svg?style=flat&label=hits&color=green")
    assert r.status_code == 200 and r.headers["Content-Type"].startswith("image/svg+xml")
    body = r.get_data(as_text=True)
    assert ">1<" in body and "hits" in body and "#10b981" in body
    assert "no-cache" in r.headers["Cache-Control"]
    client.get("/badge/acme/visits.svg?readonly=1")
    assert client.get("/api/v2/acme/visits").json["count"] == 1


@pytest.mark.parametrize("style", ["flat", "social", "big"])
def test_badge_styles(client, counter, style):
    assert "<svg" in client.get(f"/badge/acme/visits.svg?style={style}&readonly=1").get_data(as_text=True)


def test_badge_escapes_label(client, counter):
    body = client.get("/badge/acme/visits.svg?label=<script>&readonly=1").get_data(as_text=True)
    assert "<script>" not in body and "&lt;script&gt;" in body


def test_badge_private_or_missing_shows_not_found(client, ws):
    counters.create_counter(ws, "priv", visibility="private")
    assert "not found" in client.get("/badge/acme/priv.svg").get_data(as_text=True)
    assert "not found" in client.get("/badge/acme/none.svg").get_data(as_text=True)
    assert db.col("counters").find_one({"name": "priv"})["count"] == 0


def test_pixel_counts_with_props(client, counter):
    r = client.get("/p/acme/visits.gif?campaign=spring&action=buy")
    assert r.headers["Content-Type"] == "image/gif" and r.data.startswith(b"GIF89a")
    ev = db.col("events").find_one({"counter_id": counter["_id"]})
    assert ev["props"] == {"campaign": "spring", "action": "buy"}


def test_embed_js_served(client):
    r = client.get("/embed.js")
    assert r.status_code == 200 and "javascript" in r.headers["Content-Type"]


# ---------- milestones ----------

def public_dns(*a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


@pytest.mark.parametrize("url", ["http://example.com/h", "https://127.0.0.1/h", "https://10.0.0.1/x",
                                 "https://169.254.169.254/latest", "ftp://x",
                                 "https://x.com:99999/h", "https://example.com:8443/h",
                                 "https://" + "a" * 70 + ".com/h"])
def test_webhook_url_rejects_private_and_non_https(url):
    with pytest.raises(notify.MilestoneError):
        notify.validate_webhook_url(url)


def test_milestone_fires_once_and_signs(ws, counter):
    with mock.patch("socket.getaddrinfo", public_dns):
        m = notify.add_milestone(ws, counter, 2, "webhook", "https://hooks.example.com/x")
    with mock.patch("socket.getaddrinfo", public_dns), \
            mock.patch("countjar.notify._post_pinned", return_value=200) as post:
        c = counters.apply(ws, counter, "up").counter
        assert post.call_count == 0
        c = counters.apply(ws, c, "up").counter
        c = counters.apply(ws, c, "up").counter
        assert post.call_count == 1
        ip, host, path, body, headers = post.call_args.args
        assert (ip, host, path) == ("93.184.216.34", "hooks.example.com", "/x")
        assert headers["X-CountJar-Signature"] == notify.sign(m["secret"], body)


def test_milestone_concurrent_claim_fires_once(ws, counter):
    with mock.patch("socket.getaddrinfo", public_dns):
        notify.add_milestone(ws, counter, 1, "webhook", "https://hooks.example.com/x")
    with mock.patch("socket.getaddrinfo", public_dns), \
            mock.patch("countjar.notify._post_pinned", return_value=200) as post:
        c = db.col("counters").find_one({"_id": counter["_id"]})
        notify.check(ws, c, 0, 1)
        notify.check(ws, c, 0, 1)  # a second request that saw the same crossing
        assert post.call_count == 1


def test_milestone_failure_recorded_not_raised(ws, counter):
    with mock.patch("socket.getaddrinfo", public_dns):
        notify.add_milestone(ws, counter, 1, "webhook", "https://hooks.example.com/x")
    with mock.patch("socket.getaddrinfo", public_dns), \
            mock.patch("countjar.notify._post_pinned", side_effect=OSError("boom")):
        counters.apply(ws, counter, "up")
    assert "boom" in db.col("milestones").find_one()["last_error"]


def test_sms_target_must_be_member(ws, counter, owner):
    with pytest.raises(notify.MilestoneError):
        notify.add_milestone(ws, counter, 5, "sms", "+19999999999", user=owner)
    m = notify.add_milestone(ws, counter, 5, "sms", owner["phone"], user=owner)
    assert m["channel"] == "sms"


def test_milestone_already_passed_is_not_armed(ws, counter):
    c = counters.apply(ws, counter, "set", value=10).counter
    with mock.patch("socket.getaddrinfo", public_dns):
        m = notify.add_milestone(ws, c, 5, "webhook", "https://hooks.example.com/x")
    assert m["fired_at"] is not None


# ---------- stats / rate limit / tokens ----------

def test_parse_window():
    assert stats.parse_window("15m").total_seconds() == 900
    for bad in ("", "0h", "91d", "abc", "5y"):
        with pytest.raises(stats.StatsError):
            stats.parse_window(bad)


def test_history_lengths(ws, counter):
    counters.apply(ws, counter, "up")
    for rng, n in (("24h", 24), ("7d", 7), ("30d", 30)):
        s = stats.history(counter["_id"], rng)
        assert len(s) == n and sum(p["ups"] for p in s) == 1


def test_workspace_summary(ws):
    a = counters.create_counter(ws, "a")
    counters.create_counter(ws, "b")
    counters.apply(ws, a, "up", visitor="v")
    s = stats.workspace_summary(ws)
    assert s["total"] == 1 and s["events_24h"] == 1 and s["unique_24h"] == 1
    assert s["top"][0]["name"] == "a"


def test_ratelimit_window(ctx):
    assert ratelimit.hit("k", 2).allowed
    assert ratelimit.hit("k", 2).allowed
    r = ratelimit.hit("k", 2)
    assert not r.allowed and r.remaining == 0


def test_tokens_hash_only_and_revoke(ws, owner):
    doc, raw = tokens.create_token(ws, owner, "ci", ["write"])
    assert raw.startswith("cj_") and raw not in str(db.col("tokens").find_one())
    assert tokens.authenticate(raw)["_id"] == doc["_id"]
    assert tokens.allows(doc, "read") and not tokens.allows(doc, "admin")
    assert tokens.revoke(ws, str(doc["_id"]))
    assert tokens.authenticate(raw) is None
    with pytest.raises(tokens.TokenError):
        tokens.create_token(ws, owner, "x", [])


def test_workspace_limit(owner):
    from countjar import accounts
    for s in ("w1", "w2", "w3"):
        accounts.create_workspace(owner, s)
    with pytest.raises(accounts.AccountError):
        accounts.create_workspace(owner, "w4")
    with pytest.raises(accounts.AccountError):
        accounts.create_workspace(make_user("+14155550111", "B"), "demo")


@pytest.mark.parametrize("style", ["flat", "social", "big"])
def test_badge_label_cannot_break_out_of_attributes(client, style):
    resp = client.get(f'/badge/x/y.svg?style={style}&label=x"%20onload="alert(1)%27<b>')
    body = resp.get_data(as_text=True)
    assert 'onload="' not in body and "<b>" not in body
    assert "&quot;" in body


def test_badge_is_sandboxed(client):
    resp = client.get("/badge/x/y.svg")
    assert "sandbox" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_html_pages_send_security_headers(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_sms_cannot_target_another_member(ws, counter, owner):
    mate = make_user("+14155550177", "Mate")
    accounts.add_member(ws, mate["phone"])
    with pytest.raises(notify.MilestoneError):
        notify.add_milestone(ws, counter, 5, "sms", owner["phone"], user=mate)


def test_sms_alerts_are_capped_per_number(ws, counter, owner):
    sent = []
    with mock.patch.object(notify, "send_sms", lambda to, body: sent.append(to)):
        for i in range(notify.SMS_PER_DAY + 2):
            m = notify.add_milestone(ws, counter, counter["count"] + 1, "sms", owner["phone"], user=owner)
            counter = counters.apply(ws, counter, "up").counter
            db.col("milestones").delete_one({"_id": m["_id"]})
    assert len(sent) == notify.SMS_PER_DAY


def test_csv_cells_cannot_start_formulas():
    out = stats.to_csv([{"referrer": "=HYPERLINK(\"x\")", "props": {"a": "b"}, "delta": -1}],
                       ["referrer", "props", "delta"])
    assert "'=HYPERLINK" in out and ",-1" in out


def test_unique_visitors_ignores_blanks(ws, counter):
    for v in ("a", "a", "b", None, ""):
        counters.apply(ws, counter, "up", visitor=v)
    assert stats.window(counter, stats.parse_window("1h"))["unique"] == 2


def test_threshold_out_of_range_rejected(ws, counter):
    with pytest.raises(notify.MilestoneError):
        notify.add_milestone(ws, counter, 10 ** 30, "sms", "+1")


def test_default_secret_key_refused_outside_dev():
    from countjar import create_app
    with pytest.raises(RuntimeError):
        create_app({"MONGODB_URI": None, "VERIFY_DEV_MODE": False, "TESTING": False,
                    "SECRET_KEY": "dev-insecure-key"})


def test_verify_handles_non_json_error_page(app):
    from countjar import verify
    resp = mock.Mock(status_code=502, content=b"<html>Bad gateway</html>")
    resp.json.side_effect = ValueError("not json")
    with app.app_context(), mock.patch("countjar.verify.requests.post", return_value=resp):
        app.config.update(TWILIO_ACCOUNT_SID="AC", TWILIO_AUTH_TOKEN="t", TWILIO_VERIFY_SID="VA")
        with pytest.raises(verify.VerifyError):
            verify._twilio("Verifications", {})
