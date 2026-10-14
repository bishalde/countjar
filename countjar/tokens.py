"""Workspace API tokens. Only a SHA-256 hash is stored; the plaintext is shown once."""
import hashlib
import secrets
from datetime import timedelta

from bson import ObjectId

from . import db

SCOPES = ("read", "write", "admin")
# Higher scopes include lower ones.
IMPLIES = {"read": {"read"}, "write": {"read", "write"}, "admin": {"read", "write", "admin"}}


class TokenError(Exception):
    pass


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(ws, user, name, scopes):
    name = (name or "").strip()[:60]
    if not name:
        raise TokenError("Give the token a name so you can recognise it later.")
    scopes = [s for s in SCOPES if s in set(scopes or [])]
    if not scopes:
        raise TokenError("Pick at least one permission.")
    raw = "cj_" + secrets.token_urlsafe(30)
    doc = {
        "workspace_id": ws["_id"], "name": name, "prefix": raw[:10], "hash": _hash(raw),
        "scopes": scopes, "created_by": user["_id"], "created_at": db.now(),
        "last_used": None, "revoked": False,
    }
    doc["_id"] = db.col("tokens").insert_one(doc).inserted_id
    return doc, raw


def authenticate(raw):
    if not raw or not raw.startswith("cj_"):
        return None
    tok = db.col("tokens").find_one({"hash": _hash(raw), "revoked": False})
    if tok:
        now = db.now()
        last = tok.get("last_used")
        if last is None or (now - last.replace(tzinfo=now.tzinfo)) > timedelta(minutes=1):
            db.col("tokens").update_one({"_id": tok["_id"]}, {"$set": {"last_used": now}})
    return tok


def allows(tok, scope):
    return any(scope in IMPLIES[s] for s in tok.get("scopes", []))


def list_tokens(ws):
    return list(db.col("tokens").find({"workspace_id": ws["_id"], "revoked": False})
                .sort("created_at", -1))


def revoke(ws, token_id):
    try:
        oid = ObjectId(token_id)
    except Exception:
        return False
    res = db.col("tokens").update_one({"_id": oid, "workspace_id": ws["_id"]},
                                      {"$set": {"revoked": True}})
    return res.modified_count == 1
