import pytest

from countjar import accounts, counters, db
from countjar.counters import CounterError


def test_demo_seeded_once(app):
    with app.app_context():
        db._ready = False
        db.init()
        ws, c = counters.find("demo", "test-counter")
        assert c["visibility"] == "public"
        assert db.col("counters").count_documents({"name": "test-counter"}) == 1


def test_up_down_with_step_and_by(ws):
    c = counters.create_counter(ws, "a", step=5)
    c = counters.apply(ws, c, "up").counter
    assert c["count"] == 5
    c = counters.apply(ws, c, "down", by=2).counter
    assert c["count"] == 3
    assert c["ups"] == 5 and c["downs"] == 2


def test_bounds_clamp_and_noop(ws):
    c = counters.create_counter(ws, "b", min=0, max=3, step=2)
    c = counters.apply(ws, c, "up").counter
    c = counters.apply(ws, c, "up").counter
    assert c["count"] == 3
    res = counters.apply(ws, c, "up")
    assert res.counted is False and res.counter["count"] == 3
    c = counters.apply(ws, c, "down", by=10).counter
    assert c["count"] == 0


def test_set_reset_and_validation(ws):
    c = counters.create_counter(ws, "c", max=100)
    c = counters.apply(ws, c, "set", value="42").counter
    assert c["count"] == 42
    with pytest.raises(CounterError) as e:
        counters.apply(ws, c, "set", value="101")
    assert e.value.code == "out_of_bounds"
    with pytest.raises(CounterError):
        counters.apply(ws, c, "set", value="abc")
    assert counters.apply(ws, c, "reset").counter["count"] == 0


def test_unique_daily_and_once(ws):
    d = counters.create_counter(ws, "d", unique="daily")
    assert counters.apply(ws, d, "up", visitor="v1").counted
    assert not counters.apply(ws, d, "up", visitor="v1").counted
    assert counters.apply(ws, d, "up", visitor="v2").counter["count"] == 2


def test_like_vote_rate(ws):
    like = counters.create_counter(ws, "like", type="like")
    assert counters.apply(ws, like, "like", visitor="v").counted
    assert not counters.apply(ws, like, "like", visitor="v").counted

    poll = counters.create_counter(ws, "poll", type="poll")
    counters.apply(ws, poll, "vote", choice="yes", visitor="a")
    p = counters.apply(ws, poll, "vote", choice="no", visitor="b").counter
    assert (p["yes"], p["no"], p["count"]) == (1, 1, 2)
    with pytest.raises(CounterError):
        counters.apply(ws, poll, "vote", choice="maybe", visitor="c")

    rating = counters.create_counter(ws, "stars", type="rating")
    counters.apply(ws, rating, "rate", value="5", visitor="a")
    r = counters.apply(ws, rating, "rate", value="2", visitor="b").counter
    assert counters.serialize(r, "acme")["average"] == 3.5
    with pytest.raises(CounterError):
        counters.apply(ws, rating, "rate", value="6", visitor="c")


def test_unsupported_action(ws):
    poll = counters.create_counter(ws, "poll", type="poll")
    with pytest.raises(CounterError) as e:
        counters.apply(ws, poll, "up")
    assert e.value.code == "unsupported_action"


def test_counter_budget_is_five_per_user(ws, owner):
    for i in range(5):
        counters.create_counter(ws, f"n{i}")
    with pytest.raises(CounterError) as e:
        counters.create_counter(ws, "n6")
    assert e.value.code == "counter_limit" and e.value.status == 403
    # Budget spans every workspace the user owns.
    ws2 = accounts.create_workspace(owner, "acme2")
    with pytest.raises(CounterError):
        counters.create_counter(ws2, "x")


def test_duplicate_and_invalid_names(ws):
    counters.create_counter(ws, "dup")
    with pytest.raises(CounterError) as e:
        counters.create_counter(ws, "dup")
    assert e.value.status == 409
    with pytest.raises(CounterError):
        counters.create_counter(ws, "Bad Name!")


def test_min_greater_than_max_rejected(ws):
    with pytest.raises(CounterError):
        counters.create_counter(ws, "z", min=5, max=1)


def test_daily_quota(app, ws, counter):
    app.config["DAILY_LIMIT"] = 2
    counters.apply(ws, counter, "up")
    counters.apply(ws, counter, "up")
    with pytest.raises(CounterError) as e:
        counters.apply(ws, counter, "up")
    assert e.value.code == "quota_exceeded" and e.value.status == 429


def test_events_and_buckets_recorded(ws, counter):
    counters.apply(ws, counter, "up", visitor="v", referrer="example.com", props={"ref": "x"})
    ev = db.col("events").find_one({"counter_id": counter["_id"]})
    assert ev["delta"] == 1 and ev["referrer"] == "example.com" and ev["props"] == {"ref": "x"}
    assert db.col("buckets").find_one({"counter_id": counter["_id"]})["ups"] == 1


def test_clean_props_filters():
    p = counters.clean_props({"ref": "a", "token": "secret", "bad key": "x", "by": "3"},
                             {"token", "by"})
    assert p == {"ref": "a"}
