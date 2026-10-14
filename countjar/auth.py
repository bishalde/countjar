"""Passwordless sign-in: phone number → SMS code (Twilio Verify) → session."""
import re

from flask import (Blueprint, flash, redirect, render_template, request, session, url_for)

from . import accounts, config, ratelimit, verify, visitors
from .accounts import AccountError, current_user, login_required

bp = Blueprint("auth", __name__)

CODE = re.compile(r"^\d{4,10}$")

COUNTRIES = [
    ("US", "+1", "🇺🇸"), ("CA", "+1", "🇨🇦"), ("GB", "+44", "🇬🇧"), ("IN", "+91", "🇮🇳"),
    ("AU", "+61", "🇦🇺"), ("DE", "+49", "🇩🇪"), ("FR", "+33", "🇫🇷"), ("ES", "+34", "🇪🇸"),
    ("IT", "+39", "🇮🇹"), ("NL", "+31", "🇳🇱"), ("SE", "+46", "🇸🇪"), ("IE", "+353", "🇮🇪"),
    ("BR", "+55", "🇧🇷"), ("MX", "+52", "🇲🇽"), ("JP", "+81", "🇯🇵"), ("SG", "+65", "🇸🇬"),
    ("AE", "+971", "🇦🇪"), ("ZA", "+27", "🇿🇦"), ("NG", "+234", "🇳🇬"), ("NZ", "+64", "🇳🇿"),
]


def normalize_phone(dial, number):
    number = re.sub(r"[^\d+]", "", number or "")
    if number.startswith("+"):
        return number
    return (dial or "+1") + number.lstrip("0")


def mask(phone):
    return phone[:3] + "•" * max(0, len(phone) - 7) + phone[-4:]


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("web.home")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(safe_next(request.args.get("next")))
    if request.method == "POST":
        phone = normalize_phone(request.form.get("dial"), request.form.get("phone"))
        if not config.PHONE.match(phone):
            flash("Enter a valid mobile number.", "error")
            return render_template("auth/login.html", countries=COUNTRIES, form=request.form), 400
        ip = visitors.client_ip(request)
        if not (ratelimit.hit(f"otp:phone:{phone}", 5, 3600).allowed and
                ratelimit.hit(f"otp:ip:{ip}", 10, 3600).allowed):
            flash("Too many codes requested. Try again in an hour.", "error")
            return render_template("auth/login.html", countries=COUNTRIES, form=request.form), 429
        try:
            verify.send_code(phone)
        except verify.VerifyError as e:
            flash(str(e), "error")
            return render_template("auth/login.html", countries=COUNTRIES, form=request.form), 502
        session["pending_phone"] = phone
        session["next"] = safe_next(request.args.get("next"))
        return redirect(url_for("auth.verify_code"))
    return render_template("auth/login.html", countries=COUNTRIES, form={})


@bp.route("/login/verify", methods=["GET", "POST"])
def verify_code():
    phone = session.get("pending_phone")
    if not phone:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        code = re.sub(r"\D", "", request.form.get("code", ""))
        if not ratelimit.hit(f"otp:check:{phone}", 10, 3600).allowed:
            flash("Too many attempts. Request a new code in an hour.", "error")
            return render_template("auth/verify.html", phone=mask(phone)), 429
        ok = False
        if CODE.match(code):
            try:
                ok = verify.check_code(phone, code)
            except verify.VerifyError as e:
                flash(str(e), "error")
                return render_template("auth/verify.html", phone=mask(phone)), 502
        if not ok:
            flash("That code didn't match. Check the SMS and try again.", "error")
            return render_template("auth/verify.html", phone=mask(phone)), 400
        user = accounts.get_or_create_user(phone)
        target = session.get("next")
        session.clear()
        session.permanent = True
        session["uid"] = str(user["_id"])
        if not user.get("name") or not accounts.user_workspaces(user):
            return redirect(url_for("auth.onboarding"))
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(safe_next(target))
    return render_template("auth/verify.html", phone=mask(phone))


@bp.post("/login/resend")
def resend():
    phone = session.get("pending_phone")
    if not phone:
        return redirect(url_for("auth.login"))
    if ratelimit.hit(f"otp:phone:{phone}", 5, 3600).allowed:
        try:
            verify.send_code(phone)
            flash("New code sent.", "success")
        except verify.VerifyError as e:
            flash(str(e), "error")
    else:
        flash("Too many codes requested. Try again in an hour.", "error")
    return redirect(url_for("auth.verify_code"))


@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    user = current_user()
    has_ws = bool(accounts.user_workspaces(user))
    if user.get("name") and has_ws:
        return redirect(url_for("web.home"))
    if request.method == "POST":
        try:
            accounts.update_profile(user, request.form.get("name"))
            if not has_ws:
                accounts.create_workspace(user, request.form.get("workspace"),
                                          request.form.get("workspace_name"))
        except AccountError as e:
            flash(str(e), "error")
            return render_template("auth/onboarding.html", has_ws=has_ws, form=request.form), 400
        flash("You're all set. Create your first counter!", "success")
        return redirect(url_for("web.home"))
    return render_template("auth/onboarding.html", has_ws=has_ws, form={})


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("site.landing"))
