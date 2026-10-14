"""Embeds that work without a token on public counters: widget script, SVG badge, pixel."""
import base64
from xml.sax.saxutils import escape

from flask import Blueprint, current_app, make_response, request, send_from_directory

from . import abbreviate, counters, ratelimit, visitors
from .counters import CounterError

bp = Blueprint("embed", __name__)

PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
COLOR = {"amber": "#f59e0b", "green": "#10b981", "blue": "#3b82f6", "red": "#ef4444",
         "violet": "#8b5cf6", "pink": "#ec4899", "slate": "#64748b", "black": "#18181b"}


@bp.get("/embed.js")
def embed_js():
    resp = send_from_directory(current_app.static_folder, "embed.js", max_age=3600)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    return resp


def _hit(ws_slug, name, readonly, props=None):
    """Return (counter, ws) after optionally counting a hit. Counter is None if unavailable."""
    ws, counter = counters.find(ws_slug, name)
    if not counter or counter["visibility"] != "public":
        return None
    if readonly or counter["type"] not in ("count", "like"):
        return counter
    rl = ratelimit.hit(f"embed:{visitors.client_ip(request)}:{request.path}",
                       current_app.config["RATE_LIMIT"])
    if not rl.allowed:
        return counter
    action = "up" if counter["type"] == "count" else "like"
    try:
        return counters.apply(ws, counter, action, visitor=visitors.visitor_hash(request),
                              referrer=visitors.referrer_host(request), props=props).counter
    except CounterError:
        return counter  # over quota etc.: still show the current value


def _color(v, default):
    if not v:
        return default
    if v in COLOR:
        return COLOR[v]
    v = v.lstrip("#")
    if len(v) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in v):
        return "#" + v
    return default


def _value_text(counter, abbrev):
    if counter is None:
        return "not found"
    t = counter["type"]
    if t == "poll":
        total = counter.get("yes", 0) + counter.get("no", 0)
        return f"{round(100 * counter.get('yes', 0) / total) if total else 0}% yes"
    if t == "rating":
        n = counter.get("rating_count", 0)
        return f"{(counter.get('rating_sum', 0) / n) if n else 0:.1f} ★"
    n = counter["count"]
    return abbreviate(n) if abbrev else f"{n:,}"


def _w(text, size=11):
    # Approximate Verdana advance width; good enough for badge layout.
    return int(len(text) * size * 0.62) + 12


def render_badge(label, value, style, label_color, color):
    label, value = escape(label), escape(value)
    if style == "big":
        lw, vw = _w(label, 12), _w(value, 18) + 8
        w, h = lw + vw, 36
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" role="img" aria-label="{label}: {value}">
<title>{label}: {value}</title>
<clipPath id="r"><rect width="{w}" height="{h}" rx="8"/></clipPath>
<g clip-path="url(#r)"><rect width="{lw}" height="{h}" fill="{label_color}"/><rect x="{lw}" width="{vw}" height="{h}" fill="{color}"/></g>
<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" text-anchor="middle">
<text x="{lw / 2}" y="22" font-size="12" opacity=".9">{label}</text>
<text x="{lw + vw / 2}" y="24" font-size="18" font-weight="bold">{value}</text></g></svg>'''
    if style == "social":
        lw, vw = _w(label), _w(value)
        w = lw + vw + 6
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{label}: {value}">
<title>{label}: {value}</title>
<rect x=".5" y=".5" width="{lw - 1}" height="19" rx="2" fill="#fcfcfc" stroke="#d5d5d5"/>
<rect x="{lw + 5.5}" y=".5" width="{vw - 1}" height="19" rx="2" fill="#fafafa" stroke="#d5d5d5"/>
<path d="M{lw + 5.5} 7.5 l-3 2.5 3 2.5" fill="#fafafa" stroke="#d5d5d5"/>
<g fill="#333" font-family="Helvetica,Arial,sans-serif" font-size="11" font-weight="bold" text-anchor="middle">
<text x="{lw / 2}" y="14">{label}</text><text x="{lw + 5 + vw / 2}" y="14">{value}</text></g></svg>'''
    lw, vw = _w(label), _w(value)
    w = lw + vw
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{label}: {value}">
<title>{label}: {value}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{w}" height="20" rx="3"/></clipPath>
<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="{label_color}"/><rect x="{lw}" width="{vw}" height="20" fill="{color}"/><rect width="{w}" height="20" fill="url(#s)"/></g>
<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
<text x="{lw / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text><text x="{lw / 2}" y="14">{label}</text>
<text x="{lw + vw / 2}" y="15" fill="#010101" fill-opacity=".3">{value}</text><text x="{lw + vw / 2}" y="14">{value}</text></g></svg>'''


@bp.get("/badge/<ws_slug>/<name>.svg")
def badge(ws_slug, name):
    a = request.args
    counter = _hit(ws_slug, name, a.get("readonly") in ("1", "true"))
    label = (a.get("label") or (counter and counter["type"] in ("like",) and "likes") or "views")[:40]
    value = _value_text(counter, a.get("abbreviate") in ("1", "true"))
    color = "#9ca3af" if counter is None else _color(a.get("color"), COLOR["amber"])
    svg = render_badge(label, value, a.get("style", "flat"), _color(a.get("labelColor"), "#3f3f46"),
                       color)
    resp = make_response(svg)
    resp.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
    # GitHub's image proxy honours this, so README badges stay fresh.
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    return resp


@bp.get("/p/<ws_slug>/<name>.gif")
def pixel(ws_slug, name):
    _hit(ws_slug, name, False, counters.clean_props(request.args))
    resp = make_response(PIXEL)
    resp.headers["Content-Type"] = "image/gif"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    return resp
