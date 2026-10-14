"""Fixed-window rate limiting stored in MongoDB, shared across serverless instances."""
import time
from collections import namedtuple
from datetime import datetime, timezone

from pymongo import ReturnDocument

from . import db

Limit = namedtuple("Limit", "allowed limit remaining reset")


def hit(key, limit, window=60):
    now = time.time()
    start = int(now // window) * window
    doc = db.col("ratelimits").find_one_and_update(
        {"_id": f"{key}:{start}"},
        {"$inc": {"count": 1},
         "$setOnInsert": {"expires_at": datetime.fromtimestamp(start + window * 2, timezone.utc)}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    count = doc["count"]
    reset = max(1, int(start + window - now))
    return Limit(count <= limit, limit, max(0, limit - count), reset)


def refund(key, window=60):
    """Give back one hit in the current window, e.g. when the action it guarded never happened."""
    start = int(time.time() // window) * window
    db.col("ratelimits").update_one({"_id": f"{key}:{start}", "count": {"$gt": 0}},
                                    {"$inc": {"count": -1}})


def wait_text(seconds):
    minutes = -(-seconds // 60)
    return "a minute" if minutes <= 1 else f"{minutes} minutes"
