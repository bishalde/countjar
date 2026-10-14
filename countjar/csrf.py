"""Minimal CSRF protection for the cookie-authenticated website (not the token API)."""
import hmac
import secrets

from flask import abort, request, session


def token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def init_app(app):
    app.jinja_env.globals["csrf_token"] = token

    @app.before_request
    def protect():
        if request.method in ("GET", "HEAD", "OPTIONS") or request.path.startswith("/api/"):
            return
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("csrf", "")
        if not sent or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400, description="Your session expired. Reload the page and try again.")
