"""CountJar: hosted counters with accounts, widgets and analytics."""
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from . import config, db


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(config.load())
    if test_config:
        app.config.update(test_config)

    if app.config["VERIFY_DEV_MODE"] and app.config["ON_VERCEL"]:
        raise RuntimeError("VERIFY_DEV_MODE must never be enabled on a deployment")
    if app.config["ON_VERCEL"] and app.config["SECRET_KEY"] == "dev-insecure-key":
        raise RuntimeError("Set SECRET_KEY on the deployment")

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app.config["ON_VERCEL"],
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    )

    if app.config["MONGODB_URI"]:
        db.connect(app.config["MONGODB_URI"], app.config["MONGODB_DB"])

    @app.before_request
    def ensure_db():
        if request.endpoint != "static":
            db.init()

    from . import api, auth, csrf, embed, site, web

    csrf.init_app(app)
    app.register_blueprint(site.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(web.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(embed.bp)

    register_filters(app)
    register_errors(app)
    return app


def register_errors(app):
    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.path.startswith("/api/"):
            code = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                    405: "method_not_allowed", 429: "rate_limited"}.get(e.code, "error")
            return jsonify(error={"code": code, "message": e.description}), e.code
        return render_template("error.html", error=e), e.code


def abbreviate(n):
    n = n or 0
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if abs(n) >= div:
            v = n / div
            return f"{v:.1f}".rstrip("0").rstrip(".") + suffix
    return str(n)


def timeago(dt):
    if not dt:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit} ago"
    return "just now"


def register_filters(app):
    app.jinja_env.filters["abbreviate"] = abbreviate
    app.jinja_env.filters["timeago"] = timeago
    app.jinja_env.filters["intcomma"] = lambda n: f"{n or 0:,}"
