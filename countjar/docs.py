"""The user manual at /docs: one template per page, navigation and SEO built from PAGES."""
from flask import Blueprint, abort, render_template
from markupsafe import Markup, escape

from . import config
from .site import site_url

bp = Blueprint("docs", __name__)

# (slug, sidebar title, page title, meta description). Order is reading order.
PAGES = [
    ("start", "Getting started", "Getting started with the CountJar counter API",
     "Create a CountJar account, make your first counter and count something in under five minutes."),
    ("auth", "Accounts and tokens", "Sign-in, workspaces and API tokens",
     "How CountJar accounts work: phone sign-in codes, workspaces, teammates, and API tokens with "
     "read, write and admin permissions sent as a Bearer header."),
    ("api", "API reference", "CountJar REST API reference",
     "Every CountJar API endpoint: read, up, down, set, reset, like, vote, rate, stats, history, "
     "events and counter management, with request and response examples."),
    ("integrations", "Code examples", "Counter API code examples",
     "Copy-paste CountJar examples for curl, browser JavaScript, Node.js, Python, React, Next.js, "
     "Go and PHP."),
    ("widgets", "Widgets and badges", "Embeddable counter widgets, SVG badges and tracking pixel",
     "Add a view counter, like button, poll or star rating to any page, a live badge to a GitHub "
     "README, or a tracking pixel to emails."),
    ("milestones", "Milestone alerts", "Milestone webhooks and SMS alerts",
     "Get a webhook or a text message when a counter reaches a number, and verify the webhook "
     "signature."),
    ("limits", "Limits and errors", "Limits, rate limits and error codes",
     "CountJar's free plan limits, API rate limits, error format and every error code, plus answers "
     "to common questions."),
]
BY_SLUG = {p[0]: p for p in PAGES}


@bp.app_template_filter("code_text")
def code_text(block):
    """Show a code sample as text: snippets like <div> or <?php must not become live markup."""
    return escape(Markup(block).unescape())


def url(slug):
    return "/docs" if slug == "start" else f"/docs/{slug}"


def jsonld(slug, title, description):
    base = site_url()
    crumbs = [("CountJar", base + "/"), ("Docs", base + "/docs")]
    if slug != "start":
        crumbs.append((BY_SLUG[slug][1], base + url(slug)))
    return {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "TechArticle", "headline": title, "description": description,
             "url": base + url(slug), "inLanguage": "en",
             "publisher": {"@type": "Organization", "name": "CountJar", "url": base + "/"}},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": i, "name": name, "item": link}
                for i, (name, link) in enumerate(crumbs, 1)]},
        ],
    }


@bp.get("/docs", defaults={"slug": "start"})
@bp.get("/docs/<slug>")
def page(slug):
    if slug not in BY_SLUG:
        abort(404)
    i = [p[0] for p in PAGES].index(slug)
    _, nav_title, title, description = BY_SLUG[slug]
    return render_template(
        f"docs/{slug}.html", slug=slug, nav_title=nav_title, page_title=title,
        page_description=description, pages=PAGES, url=url,
        prev=PAGES[i - 1] if i else None, next=PAGES[i + 1] if i + 1 < len(PAGES) else None,
        jsonld=jsonld(slug, title, description),
        demo_ws=config.DEMO_WORKSPACE, demo_counter=config.DEMO_COUNTER)
