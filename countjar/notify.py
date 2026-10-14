"""Milestones: when a counter crosses a threshold, call a webhook or send an SMS once."""
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
from urllib.parse import urlparse

import certifi
import requests
import urllib3
from bson import ObjectId
from flask import current_app

from . import counters, db, ratelimit

log = logging.getLogger(__name__)

CHANNELS = ("webhook", "sms")
SMS_PER_DAY = 5  # per recipient, across all workspaces
MAX_PER_COUNTER = 10


class MilestoneError(Exception):
    pass


def _public_ip(host):
    """Resolve once and refuse anything that isn't a public internet address."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise MilestoneError("That webhook host doesn't resolve.") from None
    ips = [info[4][0] for info in infos]
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        raise MilestoneError("Webhook URL must point to a public internet address.")
    return ips[0]


def validate_webhook_url(url):
    """Allow only https URLs on port 443 that resolve to public addresses (no SSRF)."""
    parsed = urlparse((url or "").strip())
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise MilestoneError("That webhook URL isn't valid.") from None
    if parsed.scheme != "https" or not host:
        raise MilestoneError("Webhook URL must start with https://")
    if port not in (None, 443):
        raise MilestoneError("Webhook URLs must use the standard https port (443).")
    _public_ip(host)
    return parsed.geturl()


def add_milestone(ws, counter, threshold, channel, target, user=None):
    try:
        threshold = int(threshold)
    except (TypeError, ValueError, OverflowError):
        raise MilestoneError("Threshold must be a whole number.") from None
    if abs(threshold) > counters.BOUND:
        raise MilestoneError("That threshold is too large.")
    if channel not in CHANNELS:
        raise MilestoneError("Pick webhook or SMS.")
    if db.col("milestones").count_documents({"counter_id": counter["_id"]}) >= MAX_PER_COUNTER:
        raise MilestoneError(f"A counter can have up to {MAX_PER_COUNTER} milestones.")
    if channel == "webhook":
        target = validate_webhook_url(target)
    else:
        # Only to the signed-in person's own verified number, so alerts can't be aimed at anyone else.
        if not user or target != user["phone"]:
            raise MilestoneError("Text alerts can only go to your own phone number.")
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
            if not ratelimit.hit(f"sms:{m['target']}", SMS_PER_DAY, 86400).allowed:
                raise MilestoneError(f"Skipped: this number already got {SMS_PER_DAY} alerts today.")
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
    parsed = urlparse(url)
    # Connect to the address we just checked, so a DNS answer that changes between the
    # check and the request (DNS rebinding) can't send us to a private address.
    status = _post_pinned(_public_ip(parsed.hostname), parsed.hostname,
                          (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else ""), body, {
        "Content-Type": "application/json",
        "User-Agent": "CountJar-Webhook/1.0",
        "X-CountJar-Signature": sign(m["secret"], body),
    })
    if status >= 400:
        raise MilestoneError(f"Webhook returned HTTP {status}")


def _post_pinned(ip, host, path, body, headers):
    pool = urllib3.HTTPSConnectionPool(
        ip, 443, server_hostname=host, assert_hostname=host, cert_reqs="CERT_REQUIRED",
        ca_certs=certifi.where(), timeout=urllib3.Timeout(connect=2, read=3), retries=False)
    try:
        resp = pool.request("POST", path, body=body, headers={**headers, "Host": host},
                            redirect=False)
    finally:
        pool.close()
    return resp.status


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
