"""Public marketing pages + SEO plumbing (robots.txt, sitemap.xml, keyword landing pages)."""
import logging
import re

from flask import Blueprint, abort, current_app, make_response, redirect, render_template, request, url_for

from . import config, counters, visitors
from .accounts import current_user

log = logging.getLogger(__name__)

bp = Blueprint("site", __name__)

# Keyword landing pages. Each targets a search intent and carries real, useful content.
SOLUTIONS = {
    "counter-api": {
        "title": "Free Counter API — count anything with one HTTP request",
        "h1": "The counter API for developers",
        "description": "A fast REST counter API: increment, decrement, set and read counters "
                       "with one HTTP call. Private counters, API tokens, stats and history.",
        "keywords": ["counter api", "rest counter api", "increment api", "count api", "hit counter api"],
        "intro": "CountJar gives every counter its own URL. Call it from a browser, a backend, a cron "
                 "job or a shell script and get a JSON number back in milliseconds.",
        "points": [
            ("Up, down, set, reset", "Every operation you need, with custom step sizes and min/max bounds."),
            ("Public or private", "Public counters work from any website. Private ones need a scoped token."),
            ("Stats & history", "Hourly and daily series, unique visitors and time windows like ?window=24h."),
            ("Generous limits", "600 requests per minute per path, with standard rate-limit headers."),
        ],
        "widget": "count",
        "faq": [
            ("Is the counter API free?", "Yes. Every account gets 5 counters and 10,000 counts a day for free."),
            ("Do I need an API key?", "Public counters can be read and incremented without one. Private counters and admin operations use a workspace token sent as a Bearer header."),
            ("Does it support CORS?", "Yes. Every API response sends Access-Control-Allow-Origin: *, so you can call it straight from the browser."),
        ],
    },
    "website-hit-counter": {
        "title": "Website Hit Counter & Visitor Counter — free, no tracking cookies",
        "h1": "A hit counter for any website",
        "description": "Add a page view or visitor counter to any website with one line of HTML. "
                       "Unique visitor mode, abbreviations, themes and live analytics.",
        "keywords": ["hit counter", "website visitor counter", "page view counter", "free hit counter for website"],
        "intro": "Drop one script tag on your page and CountJar shows a live, animated view count — "
                 "and records hourly analytics behind it. No cookies, no personal data.",
        "points": [
            ("One line of HTML", "Works on static sites, WordPress, Ghost, Webflow, Hugo, Jekyll and more."),
            ("Unique visitors", "Count every hit, or each visitor once per day or once ever."),
            ("Looks native", "Light, dark and glass themes, custom colours, icons and labels."),
            ("Privacy-friendly", "Visitors are identified by a salted hash; IP addresses are never stored."),
        ],
        "widget": "count",
        "faq": [
            ("Will it slow my site down?", "No. The widget script is small, loads async and renders in a Shadow DOM."),
            ("Can I count unique visitors?", "Yes. Set the counter's unique mode to daily or once."),
        ],
    },
    "github-profile-views-badge": {
        "title": "GitHub Profile Views Badge — README view counter",
        "h1": "A view counter badge for your GitHub README",
        "description": "Show how many people viewed your GitHub profile or repository with an "
                       "SVG badge. Flat, social and big styles with custom colours.",
        "keywords": ["github profile views", "readme view counter", "profile views badge", "visitor badge"],
        "intro": "Paste one Markdown image into your README. Every view increments the counter and "
                 "the badge always shows the latest number.",
        "points": [
            ("Three styles", "flat, social and big — pick the one that fits your profile."),
            ("Your colours", "Named colours or any hex value for both the label and the number."),
            ("Read-only mode", "Show a count without incrementing it with ?readonly=1."),
            ("Always fresh", "Sent with no-cache headers so GitHub's image proxy doesn't freeze it."),
        ],
        "widget": "badge",
        "faq": [
            ("Does it work on GitHub?", "Yes. Badges are plain SVG images, so they work in any Markdown renderer, Notion and docs sites."),
        ],
    },
    "like-button-widget": {
        "title": "Like Button Widget for Any Website — embeddable upvotes",
        "h1": "An embeddable like button",
        "description": "Add a like or upvote button to articles, docs and products. One like per "
                       "visitor, live counts, themes and analytics.",
        "keywords": ["like button widget", "upvote button", "embed like button", "clap button for blog"],
        "intro": "Let readers tell you what they love. Each visitor can like once, and you get a "
                 "timeline of likes in the dashboard.",
        "points": [
            ("One like per visitor", "Duplicate clicks are ignored server-side."),
            ("Instant feedback", "Optimistic UI with a little pop animation."),
            ("Milestones", "Get a webhook or SMS when a post hits 100 likes."),
            ("Any stack", "Plain HTML embed, or call /like from your own button."),
        ],
        "widget": "like",
        "faq": [],
    },
    "poll-widget": {
        "title": "Yes/No Poll Widget — embeddable feedback poll",
        "h1": "A yes/no poll you can embed anywhere",
        "description": "Ask “Was this helpful?” or any yes/no question and show live results. "
                       "One vote per visitor, results in your dashboard.",
        "keywords": ["poll widget", "was this helpful widget", "yes no poll embed", "feedback widget"],
        "intro": "The quickest way to collect feedback on docs, articles and product pages.",
        "points": [
            ("Live results", "Visitors see the percentage split after voting."),
            ("One vote each", "Each visitor gets one vote."),
            ("Exportable", "Download every vote with its properties as CSV or JSON."),
            ("Custom question", "Set the question per page with data-question."),
        ],
        "widget": "poll",
        "faq": [],
    },
    "star-rating-widget": {
        "title": "Star Rating Widget — 5-star ratings for any page",
        "h1": "Five-star ratings for any page",
        "description": "Embed a 1–5 star rating widget that shows the live average and number of "
                       "ratings. One rating per visitor.",
        "keywords": ["star rating widget", "rating widget for website", "5 star rating embed"],
        "intro": "Collect ratings on tutorials, recipes, products or anything else, with the "
                 "average updating in real time.",
        "points": [
            ("Live average", "Shows the current average and total ratings."),
            ("Fair", "One rating per visitor."),
            ("Badge too", "Show the average as an SVG badge anywhere."),
            ("API access", "Read average and count from /api/v2."),
        ],
        "widget": "rating",
        "faq": [],
    },
}


def site_url():
    return (current_app.config.get("SITE_URL") or request.url_root).rstrip("/")


# ---------- CountJar counting its own visitors ----------

COUNTED_PAGES = {"site.landing", "site.solution", "site.pricing"}
BOT = re.compile(r"bot|crawl|spider|slurp|preview|monitor|curl|wget|python-requests|headless", re.I)


@bp.before_app_request
def count_visit():
    if request.method != "GET" or request.endpoint not in COUNTED_PAGES:
        return
    ua = request.headers.get("User-Agent", "")
    if not ua or BOT.search(ua):
        return
    try:
        ws, counter = counters.find(config.DEMO_WORKSPACE, config.SITE_COUNTER)
        if counter:
            counters.apply(ws, counter, "up", visitor=visitors.visitor_hash(request),
                           referrer=visitors.referrer_host(request))
    except Exception:  # the visitor tally must never take a page down
        log.exception("couldn't count site visit")


def site_visitor_count():
    _, counter = counters.find(config.DEMO_WORKSPACE, config.SITE_COUNTER)
    return counter["count"] if counter else 0


@bp.app_context_processor
def seo_context():
    return {
        "site_url": site_url(),
        "google_verification": current_app.config.get("GOOGLE_SITE_VERIFICATION"),
        "bing_verification": current_app.config.get("BING_SITE_VERIFICATION"),
        "solutions_nav": [(k, v["h1"]) for k, v in SOLUTIONS.items()],
        "site_visitor_count": site_visitor_count,  # called lazily, only by templates that show it
    }


@bp.get("/")
def landing():
    _, demo = counters.find(config.DEMO_WORKSPACE, config.DEMO_COUNTER)
    return render_template("landing.html", demo=demo, signed_in=bool(current_user()))


@bp.get("/solutions/<slug>")
def solution(slug):
    s = SOLUTIONS.get(slug)
    if not s:
        abort(404, description="Page not found.")
    url = site_url() + request.path
    graph = [
        {"@type": "WebPage", "name": s["title"], "description": s["description"], "url": url},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "CountJar", "item": site_url() + "/"},
            {"@type": "ListItem", "position": 2, "name": s["h1"], "item": url},
        ]},
    ]
    if s["faq"]:
        graph.append({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in s["faq"]]})
    return render_template("solution.html", s=s, slug=slug,
                           jsonld={"@context": "https://schema.org", "@graph": graph},
                           others=[(k, v["h1"]) for k, v in SOLUTIONS.items() if k != slug])


@bp.get("/pricing")
def pricing():
    return render_template("pricing.html")


@bp.get("/jar/<path:_>")
def old_jar(_):
    return redirect(url_for("site.landing"), 301)


@bp.get("/robots.txt")
def robots():
    body = "\n".join([
        "User-agent: *",
        "Allow: /",
        "Disallow: /app/",
        "Disallow: /api/",
        "Disallow: /login",
        "Disallow: /onboarding",
        "Disallow: /p/",
        f"Sitemap: {site_url()}/sitemap.xml",
        "",
    ])
    resp = make_response(body)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    return resp


def sitemap_urls():
    urls = [("/", "1.0", "weekly"), ("/pricing", "0.6", "monthly")]
    urls += [(f"/solutions/{k}", "0.8", "monthly") for k in SOLUTIONS]
    return urls


@bp.get("/sitemap.xml")
def sitemap():
    base = site_url()
    items = "".join(
        f"<url><loc>{base}{path}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        for path, prio, freq in sitemap_urls())
    resp = make_response('<?xml version="1.0" encoding="UTF-8"?>'
                         f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>')
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    return resp
