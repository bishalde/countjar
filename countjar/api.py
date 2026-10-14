"""REST API v2: /api/v2/<workspace>/<counter>/...

Auth is a workspace token (`Authorization: Bearer cj_...` or `?token=`). Session cookies
are deliberately ignored so a third-party page can't make a signed-in user's browser
change counters. Public counters can be read and hit (up/like/vote/rate) without a token.
"""
from flask import Blueprint, current_app, g, jsonify, make_response, request

from . import config, counters, ratelimit, stats, tokens, visitors
from .counters import CounterError

bp = Blueprint("api", __name__, url_prefix="/api/v2")

RESERVED_PARAMS = {"token", "by", "value", "choice", "window", "format", "range", "limit"}


class ApiError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@bp.errorhandler(ApiError)
def api_error(e):
    resp = jsonify(error={"code": e.code, "message": e.message})
    resp.status_code = e.status
    if e.status == 429 and "rate" in g:
        resp.headers["Retry-After"] = str(g.rate.reset)
    return resp


@bp.errorhandler(CounterError)
def counter_error(e):
    return api_error(ApiError(e.code, e.message, e.status))


@bp.after_request
def headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Expose-Headers"] = "X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After"
    resp.headers["Cache-Control"] = "no-store"
    if "rate" in g:
        resp.headers["X-RateLimit-Limit"] = str(g.rate.limit)
        resp.headers["X-RateLimit-Remaining"] = str(g.rate.remaining)
    return resp


# ---------- helpers ----------

def _token_from_request():
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.args.get("token")


def caller(ws):
    raw = _token_from_request()
    if not raw:
        return None
    tok = tokens.authenticate(raw)
    if not tok:
        raise ApiError("invalid_token", "That API token is invalid or has been revoked.", 401)
    if tok["workspace_id"] != ws["_id"]:
        raise ApiError("wrong_workspace", "This token belongs to a different workspace.", 403)
    return tok


def limit(tok):
    who = str(tok["_id"]) if tok else visitors.client_ip(request)
    g.rate = ratelimit.hit(f"api:{who}:{request.path}", current_app.config["RATE_LIMIT"])
    if not g.rate.allowed:
        raise ApiError("rate_limited", "Too many requests. Slow down and retry shortly.", 429)


def need(tok, scope, what):
    if tok is None:
        raise ApiError("unauthorized", f"{what} needs an API token with '{scope}' permission.", 401)
    if not tokens.allows(tok, scope):
        raise ApiError("forbidden", f"This token doesn't have '{scope}' permission.", 403)


def load(ws_slug, name):
    ws, counter = counters.find(ws_slug, name)
    if not ws:
        raise ApiError("not_found", f"Workspace “{ws_slug}” not found.", 404)
    tok = caller(ws)
    limit(tok)
    if not counter:
        raise ApiError("not_found", f"Counter “{name}” not found in “{ws_slug}”.", 404)
    if counter["visibility"] == "private":
        need(tok, "read", "This private counter")
    return ws, counter, tok


def params():
    data = dict(request.args)
    if request.is_json:
        data.update({k: v for k, v in (request.get_json(silent=True) or {}).items()
                     if isinstance(v, (str, int, float, bool))})
    elif request.form:
        data.update(request.form)
    return data


def window_block(counter, p):
    if not p.get("window"):
        return {}
    try:
        td = stats.parse_window(p["window"])
    except stats.StatsError as e:
        raise ApiError("invalid_window", str(e), 400) from None
    w = stats.window(counter, td)
    return {"window": {"range": p["window"], "count": w["net"], "events": w["events"],
                       "unique": w["unique"]}}


def csv_response(body, filename):
    resp = make_response(body)
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------- read ----------

@bp.get("/<ws_slug>/<name>")
def read(ws_slug, name):
    ws, counter, _ = load(ws_slug, name)
    return jsonify(**counters.serialize(counter, ws_slug), **window_block(counter, params()))


def do_stats(ws, counter, tok):
    return jsonify(workspace=ws["slug"], name=counter["name"], **stats.counter_stats(counter))


def do_history(ws, counter, tok):
    p = params()
    try:
        series = stats.history(counter["_id"], p.get("range", "24h"))
    except stats.StatsError as e:
        raise ApiError("invalid_range", str(e), 400) from None
    if p.get("format") == "csv":
        return csv_response(stats.to_csv(series, ["t", "ups", "downs", "net", "events"]),
                            f"{ws['slug']}-{counter['name']}-history.csv")
    return jsonify(workspace=ws["slug"], name=counter["name"], range=p.get("range", "24h"),
                   series=series)


def do_events(ws, counter, tok):
    need(tok, "read", "Reading raw events")
    p = params()
    try:
        n = max(1, min(int(p.get("limit", 100)), 1000))
    except ValueError:
        n = 100
    rows = stats.event_rows(stats.recent_events([counter["_id"]], n, p.get("filter")))
    if p.get("format") == "csv":
        return csv_response(stats.to_csv(rows, stats.EVENT_FIELDS),
                            f"{ws['slug']}-{counter['name']}-events.csv")
    return jsonify(workspace=ws["slug"], name=counter["name"], events=rows)


# ---------- write ----------

def mutate(action):
    def handler(ws, counter, tok):
        p = params()
        public = counter["visibility"] == "public"
        if action in counters.PUBLIC_ACTIONS and public:
            if p.get("by") is not None:
                need(tok, "write", "Custom step sizes")
        elif action == "down" and counters.is_demo(ws):
            pass  # the demo counter is a free-for-all
        else:
            need(tok, "write", f"“{action}”")
        res = counters.apply(
            ws, counter, action,
            by=p.get("by"), value=p.get("value"), choice=p.get("choice"),
            visitor=visitors.visitor_hash(request),
            referrer=visitors.referrer_host(request),
            props=counters.clean_props(p, RESERVED_PARAMS),
        )
        return jsonify(**counters.serialize(res.counter, ws["slug"]), counted=res.counted)
    return handler


HANDLERS = {
    "stats": do_stats,
    "history": do_history,
    "events": do_events,
    **{a: mutate(a) for a in ("up", "down", "set", "reset", "like", "vote", "rate")},
}
READ_ONLY = {"stats", "history", "events"}


@bp.route("/<ws_slug>/<name>/<action>", methods=["GET", "POST"])
def counter_action(ws_slug, name, action):
    handler = HANDLERS.get(action)
    if not handler:
        raise ApiError("not_found", f"Unknown endpoint “{action}”.", 404)
    if action in READ_ONLY and request.method != "GET":
        raise ApiError("method_not_allowed", "Use GET.", 405)
    ws, counter, tok = load(ws_slug, name)
    return handler(ws, counter, tok)


# ---------- workspace ----------

@bp.get("/<ws_slug>")
def workspace(ws_slug):
    ws = counters.accounts.get_workspace(ws_slug)
    if not ws:
        raise ApiError("not_found", f"Workspace “{ws_slug}” not found.", 404)
    tok = caller(ws)
    limit(tok)
    include_private = bool(tok and tokens.allows(tok, "read"))
    s = stats.workspace_summary(ws, include_private)
    return jsonify(
        workspace=ws_slug,
        total=s["total"], active_24h=s["active_24h"], events_24h=s["events_24h"],
        unique_24h=s["unique_24h"],
        top=[{"name": c["name"], "count": c["count"]} for c in s["top"]],
        counters=[counters.serialize(c, ws_slug) for c in s["counters"]],
    )


def admin(ws_slug):
    ws = counters.accounts.get_workspace(ws_slug)
    if not ws or ws["slug"] == config.DEMO_WORKSPACE:
        raise ApiError("not_found", f"Workspace “{ws_slug}” not found.", 404)
    tok = caller(ws)
    limit(tok)
    need(tok, "admin", "Managing counters")
    return ws


@bp.post("/<ws_slug>/counters")
def create(ws_slug):
    ws = admin(ws_slug)
    body = request.get_json(silent=True) or {}
    c = counters.create_counter(ws, body.get("name"), **{
        k: body[k] for k in ("type", "visibility", "description", "step", "min", "max", "unique",
                             "start") if k in body})
    return jsonify(**counters.serialize(c, ws_slug)), 201


@bp.patch("/<ws_slug>/<name>")
def update(ws_slug, name):
    ws = admin(ws_slug)
    _, counter = counters.find(ws_slug, name)
    if not counter:
        raise ApiError("not_found", f"Counter “{name}” not found.", 404)
    body = request.get_json(silent=True) or {}
    c = counters.update_counter(counter, {
        k: body[k] for k in ("visibility", "description", "step", "min", "max", "unique") if k in body})
    return jsonify(**counters.serialize(c, ws_slug))


@bp.delete("/<ws_slug>/<name>")
def delete(ws_slug, name):
    admin(ws_slug)
    _, counter = counters.find(ws_slug, name)
    if not counter:
        raise ApiError("not_found", f"Counter “{name}” not found.", 404)
    counters.delete_counter(counter)
    return "", 204
