"""Counter CRUD and every counter mutation.

All writes go through `apply`, which enforces bounds, unique-visitor rules and the
owner's daily quota, then records the event, the hourly bucket and milestones.
"""
import re
from collections import namedtuple
from datetime import timedelta

from flask import current_app
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from . import accounts, config, db

TYPES = ("count", "like", "poll", "rating")
VISIBILITIES = ("public", "private")
UNIQUE_MODES = ("none", "daily", "once")
MAX_STEP = 1_000_000
BOUND = 10**15

ACTIONS = {
    "count": {"up", "down", "set", "reset"},
    "like": {"like", "up", "down", "set", "reset"},
    "poll": {"vote", "reset"},
    "rating": {"rate", "reset"},
}
# Actions a visitor without a token may perform on a public counter.
PUBLIC_ACTIONS = {"up", "like", "vote", "rate"}

PROP_KEY = re.compile(r"^[A-Za-z0-9_]{1,32}$")

Result = namedtuple("Result", "counter counted")


class CounterError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------- lookup ----------

def find(ws_slug, name):
    ws = accounts.get_workspace(ws_slug)
    if not ws:
        return None, None
    return ws, db.col("counters").find_one({"workspace_id": ws["_id"], "name": name})


def list_counters(ws, include_private=True):
    q = {"workspace_id": ws["_id"]}
    if not include_private:
        q["visibility"] = "public"
    return list(db.col("counters").find(q).sort("name", 1))


def is_demo(ws):
    return ws["slug"] == config.DEMO_WORKSPACE


# ---------- settings ----------

def _int_or_none(v, field):
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise CounterError("invalid_setting", f"{field} must be a whole number.") from None
    if abs(n) > BOUND:
        raise CounterError("invalid_setting", f"{field} is too large.")
    return n


def clean_settings(data, current=None):
    """Validate user-supplied settings. `current` is the existing counter on update."""
    out = {}
    if "type" in data and current is None:
        if data["type"] not in TYPES:
            raise CounterError("invalid_setting", f"type must be one of {', '.join(TYPES)}.")
        out["type"] = data["type"]
    if "visibility" in data:
        if data["visibility"] not in VISIBILITIES:
            raise CounterError("invalid_setting", "visibility must be public or private.")
        out["visibility"] = data["visibility"]
    if "unique" in data:
        if data["unique"] not in UNIQUE_MODES:
            raise CounterError("invalid_setting", "unique must be none, daily or once.")
        out["unique"] = data["unique"]
    if "description" in data:
        out["description"] = str(data["description"] or "").strip()[:200]
    if "step" in data:
        step = _int_or_none(data["step"], "step") or 1
        if not 1 <= step <= MAX_STEP:
            raise CounterError("invalid_setting", f"step must be between 1 and {MAX_STEP:,}.")
        out["step"] = step
    for field in ("min", "max"):
        if field in data:
            out[field] = _int_or_none(data[field], field)
    lo = out.get("min", current.get("min") if current else None)
    hi = out.get("max", current.get("max") if current else None)
    if lo is not None and hi is not None and lo > hi:
        raise CounterError("invalid_setting", "min can't be greater than max.")
    return out


def create_counter(ws, name, **data):
    name = (name or "").strip().lower()
    if not config.SLUG.match(name):
        raise CounterError("invalid_name",
                           "Counter names use 1–64 lowercase letters, digits, - or _.")
    if not is_demo(ws):
        b = accounts.budget(ws["owner_id"])
        if b["left"] <= 0:
            raise CounterError(
                "counter_limit",
                f"You've used all {b['limit']} counters in your plan. Delete one to create another.",
                403)
    settings = clean_settings(data)
    start = _int_or_none(data.get("start"), "start") or 0
    lo, hi = settings.get("min"), settings.get("max")
    if (lo is not None and start < lo) or (hi is not None and start > hi):
        raise CounterError("invalid_setting", "Starting value must be within min and max.")
    doc = db.new_counter_doc(ws["_id"], name, settings)
    doc["count"] = start
    try:
        doc["_id"] = db.col("counters").insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise CounterError("exists", f"A counter named “{name}” already exists here.", 409) from None
    return doc


def update_counter(counter, data):
    settings = clean_settings(data, current=counter)
    if not settings:
        return counter
    settings["updated_at"] = db.now()
    return db.col("counters").find_one_and_update(
        {"_id": counter["_id"]}, {"$set": settings}, return_document=ReturnDocument.AFTER)


def delete_counter(counter):
    for name in ("events", "buckets", "marks", "milestones"):
        db.col(name).delete_many({"counter_id": counter["_id"]})
    db.col("counters").delete_one({"_id": counter["_id"]})


# ---------- mutations ----------

def clean_props(args, reserved=()):
    props = {}
    for k, v in args.items():
        if k in reserved or not PROP_KEY.match(k):
            continue
        props[k] = str(v)[:200]
        if len(props) >= 10:
            break
    return props


def _int_arg(v, field, lo, hi):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise CounterError("invalid_value", f"{field} must be a whole number.") from None
    if not lo <= n <= hi:
        raise CounterError("invalid_value", f"{field} must be between {lo:,} and {hi:,}.")
    return n


def _check_quota(ws):
    if is_demo(ws):
        return
    u = accounts.usage_today(ws["owner_id"])
    if u["used"] >= u["limit"]:
        raise CounterError("quota_exceeded",
                           f"Daily limit of {u['limit']:,} counts reached. It resets at 00:00 UTC.", 429)


def _claim_mark(counter, kind, visitor, ttl=None):
    """True the first time this visitor does `kind` on the counter (within ttl)."""
    if visitor is None:
        return True
    doc = {"counter_id": counter["_id"], "kind": kind, "visitor": visitor}
    if ttl:
        doc["expires_at"] = db.now() + ttl
    try:
        db.col("marks").insert_one(doc)
        return True
    except DuplicateKeyError:
        return False


def apply(ws, counter, action, *, by=None, value=None, choice=None,
          visitor=None, referrer=None, props=None):
    ctype = counter["type"]
    if action not in ACTIONS[ctype]:
        raise CounterError("unsupported_action", f"“{action}” isn't available on a {ctype} counter.")
    _check_quota(ws)

    cid = counter["_id"]
    col = db.col("counters")
    ts = db.now()
    lo, hi = counter.get("min"), counter.get("max")
    old = counter["count"]

    if action in ("up", "down"):
        delta = counter.get("step", 1) if by is None else _int_arg(by, "by", 1, MAX_STEP)
        if action == "up" and hi is not None and old >= hi:
            return Result(counter, False)
        if action == "down" and lo is not None and old <= lo:
            return Result(counter, False)
        if action == "up" and counter.get("unique", "none") != "none":
            daily = counter["unique"] == "daily"
            kind = "u:" + ts.strftime("%Y-%m-%d") if daily else "u"
            if not _claim_mark(counter, kind, visitor, timedelta(days=2) if daily else None):
                return Result(counter, False)
        signed = delta if action == "up" else -delta
        doc = col.find_one_and_update(
            {"_id": cid},
            {"$inc": {"count": signed, "ups" if action == "up" else "downs": delta},
             "$set": {"updated_at": ts}},
            return_document=ReturnDocument.AFTER)
        old = doc["count"] - signed  # value just before our atomic $inc
        # Clamp to bounds; a conditional write keeps concurrent hits from overshooting.
        if hi is not None and doc["count"] > hi:
            col.update_one({"_id": cid, "count": {"$gt": hi}}, {"$set": {"count": hi}})
            doc["count"] = hi
        if lo is not None and doc["count"] < lo:
            col.update_one({"_id": cid, "count": {"$lt": lo}}, {"$set": {"count": lo}})
            doc["count"] = lo
        record_value = None
    elif action == "set":
        if value is None:
            raise CounterError("invalid_value", "Pass the new value as ?value=.")
        record_value = _int_arg(value, "value", -BOUND, BOUND)
        if (lo is not None and record_value < lo) or (hi is not None and record_value > hi):
            raise CounterError("out_of_bounds", "value is outside this counter's min/max.")
        before = col.find_one_and_update(
            {"_id": cid}, {"$set": {"count": record_value, "updated_at": ts}},
            return_document=ReturnDocument.BEFORE)
        old = before["count"]
        doc = {**before, "count": record_value, "updated_at": ts}
    elif action == "reset":
        target = lo if lo is not None and lo > 0 else 0
        target = min(target, hi) if hi is not None else target
        fields = {"count": target, "updated_at": ts}
        if ctype == "poll":
            fields.update(yes=0, no=0)
        if ctype == "rating":
            fields.update(rating_sum=0, rating_count=0)
        before = col.find_one_and_update({"_id": cid}, {"$set": fields},
                                         return_document=ReturnDocument.BEFORE)
        old = before["count"]
        doc = {**before, **fields}
        db.col("marks").delete_many({"counter_id": cid, "kind": {"$in": ["like", "vote", "rate"]}})
        record_value = target
    elif action == "like":
        if not _claim_mark(counter, "like", visitor):
            return Result(counter, False)
        doc = col.find_one_and_update(
            {"_id": cid}, {"$inc": {"count": 1, "ups": 1}, "$set": {"updated_at": ts}},
            return_document=ReturnDocument.AFTER)
        record_value = None
    elif action == "vote":
        if choice not in ("yes", "no"):
            raise CounterError("invalid_value", "choice must be yes or no.")
        if not _claim_mark(counter, "vote", visitor):
            return Result(counter, False)
        doc = col.find_one_and_update(
            {"_id": cid}, {"$inc": {"count": 1, choice: 1}, "$set": {"updated_at": ts}},
            return_document=ReturnDocument.AFTER)
        record_value = 1 if choice == "yes" else 0
    else:  # rate
        stars = _int_arg(value, "value", 1, 5)
        if not _claim_mark(counter, "rate", visitor):
            return Result(counter, False)
        doc = col.find_one_and_update(
            {"_id": cid},
            {"$inc": {"count": 1, "rating_sum": stars, "rating_count": 1}, "$set": {"updated_at": ts}},
            return_document=ReturnDocument.AFTER)
        record_value = stars

    if action in ("like", "vote", "rate"):
        old = doc["count"] - 1  # each of these is a single atomic +1
    new = doc["count"]
    _record(ws, doc, action, new - old, record_value, visitor, referrer, props or {}, ts)
    if new > old:
        from . import notify
        notify.check(ws, doc, old, new)
    return Result(doc, True)


def _record(ws, counter, action, delta, value, visitor, referrer, props, ts):
    db.col("events").insert_one({
        "counter_id": counter["_id"], "workspace_id": ws["_id"], "ts": ts, "action": action,
        "delta": delta, "value": value, "visitor": visitor, "referrer": referrer, "props": props,
    })
    hour = ts.replace(minute=0, second=0, microsecond=0)
    db.col("buckets").update_one(
        {"counter_id": counter["_id"], "hour": hour},
        {"$inc": {"ups": max(delta, 0), "downs": max(-delta, 0), "events": 1}},
        upsert=True)
    if not is_demo(ws):
        db.col("usage").update_one(
            {"user_id": ws["owner_id"], "day": ts.strftime("%Y-%m-%d")},
            {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": ts + timedelta(days=3)}},
            upsert=True)


# ---------- output ----------

def serialize(counter, ws_slug):
    out = {
        "workspace": ws_slug,
        "name": counter["name"],
        "type": counter["type"],
        "visibility": counter["visibility"],
        "description": counter.get("description", ""),
        "count": counter["count"],
        "created_at": _iso(counter.get("created_at")),
        "updated_at": _iso(counter.get("updated_at")),
    }
    if counter["type"] == "poll":
        total = counter.get("yes", 0) + counter.get("no", 0)
        out.update(yes=counter.get("yes", 0), no=counter.get("no", 0),
                   yes_pct=round(100 * counter.get("yes", 0) / total, 1) if total else 0)
    if counter["type"] == "rating":
        n = counter.get("rating_count", 0)
        out.update(ratings=n, average=round(counter.get("rating_sum", 0) / n, 2) if n else 0)
    return out


def _iso(dt):
    if not dt:
        return None
    s = dt.isoformat()
    return s.replace("+00:00", "Z") if "+" in s else s + "Z"
