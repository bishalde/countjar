"""Users, workspaces, membership and per-user budgets."""
from functools import wraps

from bson import ObjectId
from flask import current_app, g, redirect, request, session, url_for
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from . import config, db

RESERVED_SLUGS = {"api", "app", "admin", "login", "logout", "docs", "badge", "embed", "static",
                  "p", "account", "new", "settings", config.DEMO_WORKSPACE}


class AccountError(Exception):
    pass


# ---------- users ----------

def get_or_create_user(phone):
    ts = db.now()
    return db.col("users").find_one_and_update(
        {"phone": phone},
        {"$set": {"last_login": ts}, "$setOnInsert": {"name": "", "created_at": ts}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def get_user(user_id):
    try:
        return db.col("users").find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None


def current_user():
    if "user" not in g:
        uid = session.get("uid")
        g.user = get_user(uid) if uid else None
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        if not user.get("name") and request.endpoint != "auth.onboarding":
            return redirect(url_for("auth.onboarding"))
        return view(*args, **kwargs)
    return wrapped


def update_profile(user, name):
    name = (name or "").strip()[:60]
    if not name:
        raise AccountError("Please enter your name.")
    db.col("users").update_one({"_id": user["_id"]}, {"$set": {"name": name}})


def delete_user(user):
    for ws in db.col("workspaces").find({"owner_id": user["_id"]}):
        delete_workspace(ws)
    db.col("workspaces").update_many({}, {"$pull": {"members": {"user_id": user["_id"]}}})
    db.col("tokens").update_many({"created_by": user["_id"]}, {"$set": {"revoked": True}})
    db.col("users").delete_one({"_id": user["_id"]})


# ---------- workspaces ----------

def validate_slug(slug):
    slug = (slug or "").strip().lower()
    if not config.SLUG.match(slug):
        raise AccountError("Use 1–64 lowercase letters, digits, - or _ (start with a letter or digit).")
    return slug


def create_workspace(user, slug, name=None):
    slug = validate_slug(slug)
    if slug in RESERVED_SLUGS:
        raise AccountError(f"“{slug}” is reserved. Pick another name.")
    owned = db.col("workspaces").count_documents({"owner_id": user["_id"]})
    if owned >= current_app.config["WORKSPACE_LIMIT"]:
        raise AccountError(f"You can own up to {current_app.config['WORKSPACE_LIMIT']} workspaces.")
    doc = {
        "slug": slug, "name": (name or slug).strip()[:60] or slug, "owner_id": user["_id"],
        "members": [{"user_id": user["_id"], "role": "owner"}], "created_at": db.now(),
    }
    try:
        doc["_id"] = db.col("workspaces").insert_one(doc).inserted_id
    except DuplicateKeyError:
        raise AccountError(f"The workspace “{slug}” is taken.") from None
    # Two requests at once can both pass the check above; recount and back out.
    if db.col("workspaces").count_documents({"owner_id": user["_id"]}) > current_app.config["WORKSPACE_LIMIT"]:
        db.col("workspaces").delete_one({"_id": doc["_id"]})
        raise AccountError(f"You can own up to {current_app.config['WORKSPACE_LIMIT']} workspaces.")
    return doc


def get_workspace(slug):
    return db.col("workspaces").find_one({"slug": slug})


def user_workspaces(user):
    return list(db.col("workspaces").find({"members.user_id": user["_id"]}).sort("created_at", 1))


def member_role(ws, user):
    if not ws or not user:
        return None
    for m in ws.get("members", []):
        if m["user_id"] == user["_id"]:
            return m["role"]
    return None


def rename_workspace(ws, name):
    name = (name or "").strip()[:60]
    if not name:
        raise AccountError("Name can't be empty.")
    db.col("workspaces").update_one({"_id": ws["_id"]}, {"$set": {"name": name}})


def delete_workspace(ws):
    ids = [c["_id"] for c in db.col("counters").find({"workspace_id": ws["_id"]}, {"_id": 1})]
    for name in ("events", "buckets", "marks", "milestones"):
        db.col(name).delete_many({"counter_id": {"$in": ids}})
    db.col("counters").delete_many({"workspace_id": ws["_id"]})
    db.col("tokens").delete_many({"workspace_id": ws["_id"]})
    db.col("workspaces").delete_one({"_id": ws["_id"]})


def members(ws):
    ids = [m["user_id"] for m in ws.get("members", [])]
    users = {u["_id"]: u for u in db.col("users").find({"_id": {"$in": ids}})}
    return [{"user": users[m["user_id"]], "role": m["role"]} for m in ws.get("members", [])
            if m["user_id"] in users]


def add_member(ws, phone):
    phone = (phone or "").replace(" ", "")
    if not config.PHONE.match(phone):
        raise AccountError("Enter the phone number in international format, e.g. +14155550123.")
    user = db.col("users").find_one({"phone": phone})
    if not user:
        raise AccountError("No CountJar account uses that number yet. Ask them to sign up first.")
    if member_role(ws, user):
        raise AccountError("They're already a member.")
    db.col("workspaces").update_one(
        {"_id": ws["_id"]}, {"$push": {"members": {"user_id": user["_id"], "role": "member"}}})
    return user


def remove_member(ws, user_id):
    if user_id == ws["owner_id"]:
        raise AccountError("The owner can't be removed.")
    db.col("workspaces").update_one({"_id": ws["_id"]}, {"$pull": {"members": {"user_id": user_id}}})
    # Tokens they made would otherwise outlive their access.
    db.col("tokens").update_many({"workspace_id": ws["_id"], "created_by": user_id},
                                 {"$set": {"revoked": True}})
    # Stop texting someone who no longer has access to the workspace.
    user = get_user(user_id)
    if user:
        ids = [c["_id"] for c in db.col("counters").find({"workspace_id": ws["_id"]}, {"_id": 1})]
        db.col("milestones").delete_many({"counter_id": {"$in": ids}, "channel": "sms",
                                          "target": user["phone"]})


# ---------- budgets ----------

def owned_counter_count(owner_id):
    ws_ids = [w["_id"] for w in db.col("workspaces").find({"owner_id": owner_id}, {"_id": 1})]
    return db.col("counters").count_documents({"workspace_id": {"$in": ws_ids}})


def budget(owner_id):
    limit = current_app.config["COUNTER_LIMIT"]
    used = owned_counter_count(owner_id)
    return {"used": used, "limit": limit, "left": max(0, limit - used)}


def usage_today(owner_id):
    doc = db.col("usage").find_one({"user_id": owner_id, "day": db.now().strftime("%Y-%m-%d")})
    return {"used": doc["count"] if doc else 0, "limit": current_app.config["DAILY_LIMIT"]}
