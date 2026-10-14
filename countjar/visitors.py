"""Identify visitors without storing IPs: a keyed hash of IP + user agent."""
import hashlib
import hmac
from urllib.parse import urlparse

from flask import current_app


def client_ip(request):
    # Vercel's edge overwrites X-Forwarded-For with the real client, so it's only trusted there.
    # Anywhere else a client could send its own header and dodge per-IP limits.
    if current_app.config.get("ON_VERCEL"):
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def visitor_hash(request):
    key = current_app.config["SECRET_KEY"].encode()
    raw = f"{client_ip(request)}|{request.headers.get('User-Agent', '')}".encode()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()[:20]


def referrer_host(request):
    ref = request.headers.get("Referer") or ""
    host = urlparse(ref).hostname
    return host[:120] if host else None
