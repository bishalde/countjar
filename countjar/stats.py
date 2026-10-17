"""Read-side analytics: time windows, history series, summaries and exports."""
import csv
import io
import json
import re
from datetime import timedelta

from . import counters, db

WINDOW = re.compile(r"^(\d{1,3})([mhd])$")
UNITS = {"m": "minutes", "h": "hours", "d": "days"}
MAX_WINDOW = timedelta(days=90)  # events are kept for 90 days
RANGES = {"24h": (24, "hour"), "7d": (7, "day"), "30d": (30, "day"), "90d": (90, "day")}


class StatsError(Exception):
    pass


def parse_window(s):
    m = WINDOW.match(s or "")
    if not m:
        raise StatsError("window looks like 15m, 24h or 7d.")
    td = timedelta(**{UNITS[m.group(2)]: int(m.group(1))})
    if not timedelta(0) < td <= MAX_WINDOW:
        raise StatsError("window must be between 1m and 90d.")
    return td


def window(counter, td):
    since = db.now() - td
    q = {"counter_id": counter["_id"], "ts": {"$gte": since}}
    rows = list(db.col("events").aggregate([
        {"$match": q},
        {"$group": {"_id": None, "net": {"$sum": "$delta"}, "events": {"$sum": 1}}},
    ]))
    uniques = unique_visitors(q)
    net = rows[0]["net"] if rows else 0
    events = rows[0]["events"] if rows else 0
    return {"net": net, "events": events, "unique": uniques}


def unique_visitors(q):
    rows = list(db.col("events").aggregate([
        {"$match": {**q, "visitor": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$visitor"}},
        {"$count": "n"},
    ]))
    return rows[0]["n"] if rows else 0


def _floor(dt, unit):
    dt = dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0) if unit == "day" else dt


def history(counter_ids, rng="24h"):
    """Zero-filled series for one counter id or a list of them."""
    if rng not in RANGES:
        raise StatsError("range must be 24h, 7d, 30d or 90d.")
    n, unit = RANGES[rng]
    step = timedelta(hours=1) if unit == "hour" else timedelta(days=1)
    end = _floor(db.now(), unit)
    start = end - step * (n - 1)
    ids = counter_ids if isinstance(counter_ids, list) else [counter_ids]
    series = {start + step * i: {"ups": 0, "downs": 0, "events": 0} for i in range(n)}
    for b in db.col("buckets").find({"counter_id": {"$in": ids}, "hour": {"$gte": start}}):
        hour = b["hour"]
        if hour.tzinfo is None:
            hour = hour.replace(tzinfo=start.tzinfo)
        key = _floor(hour, unit)
        if key in series:
            for f in ("ups", "downs", "events"):
                series[key][f] += b.get(f, 0)
    return [{"t": counters._iso(t), "ups": v["ups"], "downs": v["downs"],
             "net": v["ups"] - v["downs"], "events": v["events"]}
            for t, v in sorted(series.items())]


def counter_stats(counter):
    now = db.now()
    today = window(counter, max(now - _floor(now, "day"), timedelta(seconds=1)))
    day = window(counter, timedelta(hours=24))
    week = window(counter, timedelta(days=7))
    return {
        "count": counter["count"],
        "total_ups": counter.get("ups", 0),
        "total_downs": counter.get("downs", 0),
        "today": today["net"],
        "last_24h": day["net"],
        "last_7d": week["net"],
        "unique_24h": day["unique"],
        "unique_7d": week["unique"],
        "events_24h": day["events"],
        "created_at": counters._iso(counter.get("created_at")),
        "updated_at": counters._iso(counter.get("updated_at")),
    }


def workspace_summary(ws, include_private=True):
    items = counters.list_counters(ws, include_private)
    ids = [c["_id"] for c in items]
    since = db.now() - timedelta(hours=24)
    q = {"counter_id": {"$in": ids}, "ts": {"$gte": since}}
    events_24h = db.col("events").count_documents(q)
    uniques = unique_visitors(q)
    top = sorted(items, key=lambda c: c["count"], reverse=True)[:5]
    active = [c for c in items if c.get("updated_at") and
              c["updated_at"].replace(tzinfo=since.tzinfo) >= since]
    return {
        "counters": items,
        "total": sum(c["count"] for c in items if c["type"] in ("count", "like")),
        "active_24h": len(active),
        "events_24h": events_24h,
        "unique_24h": uniques,
        "top": top,
    }


def recent_events(counter_ids, limit=20, props_filter=None):
    q = {"counter_id": {"$in": counter_ids}}
    if props_filter:
        k, _, v = props_filter.partition("=")
        if k in CLIENT_FILTERS:
            q[f"client.{k}"] = v
        elif counters.PROP_KEY.match(k):
            q[f"props.{k}"] = v
    return list(db.col("events").find(q).sort("ts", -1).limit(limit))


def top_referrers(counter_id, days=7, limit=5):
    since = db.now() - timedelta(days=days)
    return list(db.col("events").aggregate([
        {"$match": {"counter_id": counter_id, "ts": {"$gte": since}, "referrer": {"$ne": None}}},
        {"$group": {"_id": "$referrer", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": limit},
    ]))


# Visitor details on each event (see visitors.details). The IP is only shown to workspace owners.
CLIENT_FIELDS = ["device", "model", "browser", "os", "country", "region", "city", "postal",
                 "lat", "lon", "tz", "lang", "page", "screen"]
CLIENT_FILTERS = {"device", "browser", "os", "country", "city"}  # ?filter=country=IN etc.
EVENT_FIELDS = ["ts", "action", "delta", "value", "visitor", "referrer", "props", *CLIENT_FIELDS]


def event_fields(include_ip=False):
    return EVENT_FIELDS + ["ip"] if include_ip else EVENT_FIELDS


def event_rows(events, include_ip=False):
    rows = []
    for e in events:
        client = e.get("client") or {}
        row = {
            "ts": counters._iso(e["ts"]), "action": e["action"], "delta": e.get("delta"),
            "value": e.get("value"), "visitor": (e.get("visitor") or "")[:12],
            "referrer": e.get("referrer") or "", "props": e.get("props") or {},
            **{f: client.get(f) for f in CLIENT_FIELDS},
        }
        if include_ip:
            row["ip"] = client.get("ip")
        rows.append(row)
    return rows


def _top(match, group, limit=None):
    pipeline = [{"$match": match}, {"$group": {"_id": group, "n": {"$sum": 1}}},
                {"$sort": {"n": -1}}]
    return list(db.col("events").aggregate(pipeline + ([{"$limit": limit}] if limit else [])))


def _version_free(name):
    # "Chrome 141" and "Chrome 140" are one browser; "Android 14" and "Android 13" are one OS.
    head, _, tail = name.rpartition(" ")
    return head if head and tail[:1].isdigit() else name


def visitor_breakdown(counter_id, days=7, limit=6):
    """Where visits came from and what they used, over the last `days`."""
    match = {"counter_id": counter_id, "ts": {"$gte": db.now() - timedelta(days=days)},
             "client": {"$type": "object"}}
    out = {"total": db.col("events").count_documents(match)}
    for key in ("country", "device", "browser", "os"):
        merged = {}
        for r in _top({**match, f"client.{key}": {"$type": "string"}}, f"$client.{key}"):
            name = _version_free(r["_id"]) if key in ("browser", "os") else r["_id"]
            merged[name] = merged.get(name, 0) + r["n"]
        out[key] = [{"name": k, "n": v} for k, v in
                    sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
    out["city"] = [{"name": r["_id"]["city"], "country": r["_id"].get("country"), "n": r["n"]}
                   for r in _top({**match, "client.city": {"$type": "string"}},
                                 {"city": "$client.city", "country": "$client.country"}, limit)]
    return out


def _cell(v):
    # Spreadsheets run cells starting with these as formulas; referrers and props are visitor input.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_csv(rows, fields):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: _cell(json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()})
    return buf.getvalue()
