"""Phone verification via Twilio Verify (SMS one-time codes)."""
import logging
import secrets

import requests
from flask import current_app

log = logging.getLogger(__name__)

VERIFY_URL = "https://verify.twilio.com/v2/Services/{sid}/{path}"

# Local development only: codes kept in memory and printed to the console.
_dev_codes = {}


class VerifyError(Exception):
    pass


def _twilio(path, data):
    cfg = current_app.config
    if not (cfg["TWILIO_ACCOUNT_SID"] and cfg["TWILIO_AUTH_TOKEN"] and cfg["TWILIO_VERIFY_SID"]):
        raise VerifyError("Phone verification is not configured on this server.")
    try:
        resp = requests.post(
            VERIFY_URL.format(sid=cfg["TWILIO_VERIFY_SID"], path=path),
            data=data,
            auth=(cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"]),
            timeout=10,
        )
    except requests.RequestException as e:
        log.warning("Twilio Verify request failed: %s", e)
        raise VerifyError("Couldn't reach the verification service. Try again.") from e
    body = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        log.warning("Twilio Verify %s -> %s %s", path, resp.status_code, body.get("message"))
        if resp.status_code == 404 and path == "VerificationCheck":
            # Twilio returns 404 once a verification has expired or been used.
            return {"status": "expired"}
        if resp.status_code == 429:
            raise VerifyError("Too many attempts. Wait a few minutes and try again.")
        raise VerifyError("That number couldn't be verified. Check it and try again.")
    return body


def send_code(phone):
    if current_app.config["VERIFY_DEV_MODE"]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        _dev_codes[phone] = code
        print(f"\n  [VERIFY_DEV_MODE] code for {phone}: {code}\n", flush=True)
        return
    _twilio("Verifications", {"To": phone, "Channel": "sms"})


def check_code(phone, code):
    if current_app.config["VERIFY_DEV_MODE"]:
        ok = _dev_codes.get(phone) == code
        if ok:
            _dev_codes.pop(phone, None)
        return ok
    return _twilio("VerificationCheck", {"To": phone, "Code": code}).get("status") == "approved"
