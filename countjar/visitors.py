"""Who made a request: a keyed visitor hash for unique counts, plus device and location details."""
import hashlib
import hmac
import re
from urllib.parse import unquote, urlparse

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


# ---------- visitor details ----------
# Shown to the workspace on each event: where the visitor was and what they used.

BOTS = [  # (pattern, name); checked before anything else
    (r"github-camo", "GitHub image proxy"),
    (r"Googlebot|Google-InspectionTool|GoogleImageProxy", "Google"),
    (r"bingbot|BingPreview", "Bing"),
    (r"facebookexternalhit|meta-externalagent", "Facebook"),
    (r"Twitterbot", "Twitter"),
    (r"Slackbot", "Slack"),
    (r"Discordbot", "Discord"),
    (r"WhatsApp", "WhatsApp"),
    (r"TelegramBot", "Telegram"),
    (r"LinkedInBot", "LinkedIn"),
    (r"^curl/", "curl"),
    (r"^Wget/", "Wget"),
    (r"python-requests|aiohttp|httpx|urllib", "Python"),
    (r"^node-fetch|undici|axios", "Node.js"),
    (r"^Go-http-client", "Go"),
    (r"HeadlessChrome", "Headless Chrome"),
    (r"(?<!cu)bot\b|crawl|spider|slurp|preview", "Bot"),
]
BOTS = [(re.compile(p, re.I), n) for p, n in BOTS]

BROWSERS = [  # order matters: Edge and Opera also say Chrome, Chrome also says Safari
    (r"EdgiOS/(\d+)|EdgA?/(\d+)", "Edge"),
    (r"OPR/(\d+)|OPiOS/(\d+)", "Opera"),
    (r"SamsungBrowser/(\d+)", "Samsung Internet"),
    (r"YaBrowser/(\d+)", "Yandex"),
    (r"Brave/(\d+)", "Brave"),
    (r"FxiOS/(\d+)|Firefox/(\d+)", "Firefox"),
    (r"CriOS/(\d+)|Chrome/(\d+)", "Chrome"),
    (r"Version/(\d+)[\d.]* (?:Mobile/\S+ )?Safari/", "Safari"),
]
BROWSERS = [(re.compile(p), n) for p, n in BROWSERS]

ANDROID_MODEL = re.compile(r"Android [\d.]+; (?:[a-z]{2}[-_][A-Za-z]{2}; )?([^;)]+?)(?: Build/[^;)]*)?\)")
WINDOWS = {"10.0": "10/11", "6.3": "8.1", "6.2": "8", "6.1": "7"}


def parse_user_agent(ua):
    """Device type, model, browser and OS from a User-Agent string."""
    ua = (ua or "")[:500]
    out = {"device": "desktop", "model": None, "browser": None, "os": None}
    if not ua:
        out["device"] = "unknown"
        return out
    for pat, name in BOTS:
        if pat.search(ua):
            out.update(device="bot", browser=name)
            return out

    if m := re.search(r"Windows NT ([\d.]+)", ua):
        out["os"] = "Windows " + WINDOWS.get(m[1], m[1])
    elif m := re.search(r"(iPhone|iPad|iPod).*? OS (\d+)[_\d]*", ua):
        out["os"], out["model"] = ("iPadOS " if m[1] == "iPad" else "iOS ") + m[2], m[1]
    elif m := re.search(r"Android (\d+(?:\.\d+)?)", ua):
        out["os"] = "Android " + m[1]
        if (mm := ANDROID_MODEL.search(ua)) and mm[1].strip() not in ("K", "wv", "Linux"):
            out["model"] = mm[1].strip()[:40]
    elif m := re.search(r"Mac OS X (\d+)[_.](\d+)", ua):
        out["os"], out["model"] = "macOS", "Mac"
    elif "CrOS" in ua:
        out["os"] = "ChromeOS"
    elif "Linux" in ua:
        out["os"] = "Linux"

    for pat, name in BROWSERS:
        if m := pat.search(ua):
            version = next((g for g in m.groups() if g), None)
            out["browser"] = f"{name} {version}" if version else name
            break

    if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        out["device"] = "tablet"
    elif re.search(r"Mobi|iPhone|iPod|Android", ua):
        out["device"] = "phone"
    return out


def _geo(request, name, limit=60):
    v = request.headers.get(f"X-Vercel-IP-{name}")
    return unquote(v)[:limit] if v else None


def _float(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def details(request, args=None):
    """Everything we record about who made a request. Location comes from Vercel's edge headers."""
    args = args or {}
    d = {"ip": client_ip(request)[:45], **parse_user_agent(request.headers.get("User-Agent"))}
    if current_app.config.get("ON_VERCEL"):  # elsewhere these headers could be forged
        d.update(country=_geo(request, "Country", 2), region=_geo(request, "Country-Region", 10),
                 city=_geo(request, "City"), postal=_geo(request, "Postal-Code", 12),
                 lat=_float(_geo(request, "Latitude")), lon=_float(_geo(request, "Longitude")),
                 tz=_geo(request, "Timezone"))
    lang = (request.headers.get("Accept-Language") or "").split(",")[0].split(";")[0].strip()
    d["lang"] = lang[:20] or None
    # Sent by the widget script and anyone who wants them: the page URL and screen size.
    page = str(args.get("_page") or "")
    d["page"] = page[:300] if page.startswith(("http://", "https://")) else None
    screen = str(args.get("_screen") or "")
    d["screen"] = screen if re.fullmatch(r"\d{2,5}x\d{2,5}", screen) else None
    return {k: v for k, v in d.items() if v is not None}
