"""MongoDB access: one client per process, collections, indexes, demo seed."""
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from . import config

_client = None
_db_name = "countjar"
_ready = False


def set_client(client, db_name="countjar"):
    """Use an existing client (tests pass a mongomock client)."""
    global _client, _db_name, _ready
    _client, _db_name, _ready = client, db_name, False


def connect(uri, db_name):
    global _client, _db_name
    if _client is None:
        # Serverless instances reuse this client across requests.
        _client = MongoClient(uri, appname="countjar", tz_aware=True,
                              serverSelectionTimeoutMS=5000)
        _db_name = db_name


def col(name):
    if _client is None:
        raise RuntimeError("MONGODB_URI is not set")
    return _client[_db_name][name]


def now():
    return datetime.now(timezone.utc)


def init():
    """Create indexes and the public demo counter. Idempotent, once per process."""
    global _ready
    if _ready:
        return
    col("users").create_index("phone", unique=True)
    col("workspaces").create_index("slug", unique=True)
    col("workspaces").create_index("members.user_id")
    col("counters").create_index([("workspace_id", ASCENDING), ("name", ASCENDING)], unique=True)
    col("events").create_index([("counter_id", ASCENDING), ("ts", DESCENDING)])
    col("events").create_index([("workspace_id", ASCENDING), ("ts", DESCENDING)])
    col("events").create_index("ts", expireAfterSeconds=90 * 86400)
    col("buckets").create_index([("counter_id", ASCENDING), ("hour", ASCENDING)], unique=True)
    col("marks").create_index(
        [("counter_id", ASCENDING), ("kind", ASCENDING), ("visitor", ASCENDING)], unique=True
    )
    col("marks").create_index("expires_at", expireAfterSeconds=0)
    col("usage").create_index([("user_id", ASCENDING), ("day", ASCENDING)], unique=True)
    col("usage").create_index("expires_at", expireAfterSeconds=0)
    col("tokens").create_index("hash", unique=True)
    col("tokens").create_index("workspace_id")
    col("milestones").create_index("counter_id")
    col("ratelimits").create_index("expires_at", expireAfterSeconds=0)
    seed_demo()
    _ready = True


def seed_demo():
    ts = now()
    try:
        col("workspaces").insert_one({
            "slug": config.DEMO_WORKSPACE, "name": "Demo", "owner_id": None,
            "members": [], "created_at": ts,
        })
    except DuplicateKeyError:
        pass
    ws = col("workspaces").find_one({"slug": config.DEMO_WORKSPACE})
    try:
        col("counters").insert_one(new_counter_doc(ws["_id"], config.DEMO_COUNTER, {
            "description": "Public demo counter. Anyone can hit it.",
        }))
    except DuplicateKeyError:
        pass


def new_counter_doc(workspace_id, name, settings):
    ts = now()
    doc = {
        "workspace_id": workspace_id, "name": name, "type": "count", "visibility": "public",
        "description": "", "count": 0, "ups": 0, "downs": 0, "step": 1, "min": None, "max": None,
        "unique": "none", "yes": 0, "no": 0, "rating_sum": 0, "rating_count": 0,
        "created_at": ts, "updated_at": ts,
    }
    doc.update(settings)
    return doc
