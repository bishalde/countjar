"""Storage layer backed by MongoDB Atlas (set MONGODB_URI)."""
import os
from datetime import datetime, timezone

from pymongo import ASCENDING, MongoClient, ReturnDocument

_client = None


def counters():
    global _client
    if _client is None:
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI is not set")
        # One client per process; serverless instances reuse it across requests.
        _client = MongoClient(uri, appname="countjar", serverSelectionTimeoutMS=5000)
    return _client[os.environ.get("MONGODB_DB", "countjar")].counters


def init():
    counters().create_index([("namespace", ASCENDING), ("name", ASCENDING)], unique=True)


def get(namespace, name):
    doc = counters().find_one({"namespace": namespace, "name": name})
    return (doc["count"], doc["created_at"], doc["updated_at"]) if doc else None


def add(namespace, name, delta):
    now = datetime.now(timezone.utc)
    doc = counters().find_one_and_update(
        {"namespace": namespace, "name": name},
        {"$inc": {"count": delta}, "$set": {"updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc["count"]


def reset(namespace, name):
    counters().update_one(
        {"namespace": namespace, "name": name},
        {"$set": {"count": 0, "updated_at": datetime.now(timezone.utc)}},
    )


def list_namespace(namespace):
    cursor = counters().find({"namespace": namespace}).sort("name", ASCENDING)
    return [(d["name"], d["count"], d["updated_at"].strftime("%Y-%m-%d %H:%M UTC")) for d in cursor]
