"""Settings read from the environment."""
import os
import re

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PHONE = re.compile(r"^\+[1-9]\d{7,14}$")

DEMO_WORKSPACE = "demo"
DEMO_COUNTER = "test-counter"
SITE_COUNTER = "site-visitors"  # private, in the demo workspace: CountJar counting its own visitors


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def load():
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "dev-insecure-key"),
        "MONGODB_URI": os.environ.get("MONGODB_URI"),
        "MONGODB_DB": os.environ.get("MONGODB_DB", "countjar"),
        "TWILIO_ACCOUNT_SID": os.environ.get("TWILIO_ACCOUNT_SID"),
        "TWILIO_AUTH_TOKEN": os.environ.get("TWILIO_AUTH_TOKEN"),
        "TWILIO_VERIFY_SID": os.environ.get("TWILIO_VERIFY_SID"),
        "TWILIO_PHONE_NUMBER": os.environ.get("TWILIO_PHONE_NUMBER"),
        "SITE_URL": os.environ.get("SITE_URL"),
        "GOOGLE_SITE_VERIFICATION": os.environ.get("GOOGLE_SITE_VERIFICATION"),
        "BING_SITE_VERIFICATION": os.environ.get("BING_SITE_VERIFICATION"),
        "VERIFY_DEV_MODE": os.environ.get("VERIFY_DEV_MODE") == "1",
        "ON_VERCEL": bool(os.environ.get("VERCEL")),
        "COUNTER_LIMIT": _int("COUNTER_LIMIT", 5),
        "WORKSPACE_LIMIT": _int("WORKSPACE_LIMIT", 3),
        "DAILY_LIMIT": _int("DAILY_LIMIT", 10_000),
        "RATE_LIMIT": _int("RATE_LIMIT", 600),
    }
