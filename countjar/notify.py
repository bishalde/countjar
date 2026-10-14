"""Milestones: when a counter crosses a threshold, call a webhook or send an SMS once."""
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
from urllib.parse import urlparse

import requests
from bson import ObjectId
from flask import current_app

from . import accounts, counters, db

log = logging.getLogger(__name__)

CHANNELS = ("webhook", "sms")
MAX_PER_COUNTER = 10


class MilestoneError(Exception):
    pass


def validate_webhook_url(url):
    """Allow only https URLs that resolve to public addresses (no SSRF into private nets)."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise MilestoneError("Webhook URL must start with https://")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise MilestoneError("That webhook host doesn't resolve.") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise MilestoneError("Webhook URL must point to a public internet address.")
    return parsed.geturl()


def add_milestone(ws, counter, threshold, channel, target):
    try:
        threshold = int(threshold)
    except (TypeError, ValueError):
        raise MilestoneError("Threshold must be a whole number.") from None
    if channel not in CHANNELS:
        raise MilestoneError("Pick webhook or SMS.")
    if db.col("milestones").count_documents({"counter_id": counter["_id"]}) >= MAX_PER_COUNTER:
        raise MilestoneError(f"A counter can have up to {MAX_PER_COUNTER} milestones.")
    if channel == "webhook":
        target = validate_webhook_url(target)
    else:
        phones = {m["user"]["phone"] for m in accounts.members(ws)}
        if target not in phones:
            raise MilestoneError("SMS alerts can only go to a verified member of this workspace.")
    doc = {
        "counter_id": counter["_id"], "threshold": threshold, "channel": channel,
        "target": target, "secret": "whsec_" + secrets.token_urlsafe(18),
        "fired_at": None, "last_error": None, "created_at": db.now(),
    }
    # Already past it? Mark as fired so it doesn't go off on the next hit.
    if counter["count"] >= threshold:
        doc["fired_at"] = db.now()
    doc["_id"] = db.col("milestones").insert_one(doc).inserted_id
    return doc


def list_milestones(counter):
    return list(db.col("milestones").find({"counter_id": counter["_id"]}).sort("threshold", 1))


def _oid(mid):
    try:
        return ObjectId(mid)
    except Exception:
        return None


def delete_milestone(counter, mid):
    db.col("milestones").delete_one({"_id": _oid(mid), "counter_id": counter["_id"]})


def rearm(counter, mid):
    db.col("milestones").update_one({"_id": _oid(mid), "counter_id": counter["_id"]},
                                    {"$set": {"fired_at": None, "last_error": None}})


def check(ws, counter, old, new):
    """Fire milestones crossed by old → new. Each fires at most once (atomic claim)."""
    crossed = db.col("milestones").find({
        "counter_id": counter["_id"], "fired_at": None,
        "threshold": {"$gt": old, "$lte": new},
    })
    for m in crossed:
        claimed = db.col("milestones").find_one_and_update(
            {"_id": m["_id"], "fired_at": None}, {"$set": {"fired_at": db.now()}})
        if claimed:
            error = _deliver(ws, counter, m, new)
            if error:
                db.col("milestones").update_one({"_id": m["_id"]}, {"$set": {"last_error": error}})


def _deliver(ws, counter, m, count):
    try:
        if m["channel"] == "webhook":
            send_webhook(ws, counter, m, count)
        else:
            send_sms(m["target"],
                     f"🫙 CountJar: {ws['slug']}/{counter['name']} just reached "
                     f"{m['threshold']:,} (now {count:,}).")
        return None
    except Exception as e:  # delivery must never break the counter write
        log.warning("milestone %s delivery failed: %s", m["_id"], e)
        return str(e)[:200]


def sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send_webhook(ws, counter, m, count):
    url = validate_webhook_url(m["target"])  # re-check: DNS may have changed since saving
    body = json.dumps({
        "event": "milestone.reached",
        "workspace": ws["slug"],
        "counter": counter["name"],
        "threshold": m["threshold"],
        "count": count,
        "fired_at": counters._iso(db.now()),
    }).encode()
    resp = requests.post(url, data=body, timeout=3, allow_redirects=False, headers={
        "Content-Type": "application/json",
        "User-Agent": "CountJar-Webhook/1.0",
        "X-CountJar-Signature": sign(m["secret"], body),
    })
    if resp.status_code >= 400:
        raise MilestoneError(f"Webhook returned HTTP {resp.status_code}")


def send_sms(to, body):
    cfg = current_app.config
    if not (cfg["TWILIO_ACCOUNT_SID"] and cfg["TWILIO_AUTH_TOKEN"] and cfg["TWILIO_PHONE_NUMBER"]):
        raise MilestoneError("SMS sending is not configured on this server.")
    resp = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{cfg['TWILIO_ACCOUNT_SID']}/Messages.json",
        data={"From": cfg["TWILIO_PHONE_NUMBER"], "To": to, "Body": body},
        auth=(cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"]),
        timeout=5,
    )
    if resp.status_code >= 400:
        raise MilestoneError(f"Twilio returned HTTP {resp.status_code}")
