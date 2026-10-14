"""Dashboard: workspaces, counters, tokens, members, account. Session auth + CSRF."""
from flask import (Blueprint, abort, flash, jsonify, make_response, redirect, render_template,
                   request, session, url_for)

from . import accounts, config, counters, notify, ratelimit, stats, tokens
from .accounts import AccountError, current_user, login_required
from .counters import CounterError

bp = Blueprint("web", __name__, url_prefix="/app")

MEMBER_ADDS_PER_HOUR = 20


@bp.after_request
def no_index(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


def workspace_or_404(slug):
    ws = accounts.get_workspace(slug)
    role = accounts.member_role(ws, current_user())
    if not role:
        abort(404, description="Workspace not found.")
    return ws, role


def counter_or_404(ws, name):
    _, counter = counters.find(ws["slug"], name)
    if not counter:
        abort(404, description="Counter not found.")
    return counter


def owner_only(role):
    if role != "owner":
        abort(403, description="Only the workspace owner can do that.")


def page(template, ws=None, role=None, **ctx):
    user = current_user()
    owner_id = ws["owner_id"] if ws else user["_id"]
    return render_template(
        template, user=user, ws=ws, role=role,
        workspaces=accounts.user_workspaces(user),
        budget=accounts.budget(owner_id), usage=accounts.usage_today(owner_id),
        **ctx)


def back(default):
    target = request.form.get("back") or ""
    return redirect(target if target.startswith("/app/") else default)


# ---------- entry ----------

@bp.get("/")
@login_required
def home():
    wss = accounts.user_workspaces(current_user())
    if not wss:
        return redirect(url_for("auth.onboarding"))
    return redirect(url_for("web.overview", ws_slug=wss[0]["slug"]))


@bp.post("/workspaces")
@login_required
def create_workspace():
    try:
        ws = accounts.create_workspace(current_user(), request.form.get("slug"),
                                       request.form.get("name"))
    except AccountError as e:
        flash(str(e), "error")
        return back(url_for("web.home"))
    flash(f"Workspace “{ws['slug']}” created.", "success")
    return redirect(url_for("web.overview", ws_slug=ws["slug"]))


# ---------- workspace ----------

@bp.get("/<ws_slug>")
@login_required
def overview(ws_slug):
    ws, role = workspace_or_404(ws_slug)
    summary = stats.workspace_summary(ws)
    ids = [c["_id"] for c in summary["counters"]]
    names = {c["_id"]: c["name"] for c in summary["counters"]}
    activity = stats.recent_events(ids, 12)
    return page("app/overview.html", ws, role, summary=summary, activity=activity, names=names)


@bp.get("/<ws_slug>/history.json")
@login_required
def workspace_history(ws_slug):
    ws, _ = workspace_or_404(ws_slug)
    ids = [c["_id"] for c in counters.list_counters(ws)]
    try:
        return jsonify(series=stats.history(ids, request.args.get("range", "24h")))
    except stats.StatsError as e:
        abort(400, description=str(e))


@bp.route("/<ws_slug>/counters", methods=["GET", "POST"])
@login_required
def counter_list(ws_slug):
    ws, role = workspace_or_404(ws_slug)
    if request.method == "POST":
        f = request.form
        try:
            c = counters.create_counter(ws, f.get("name"), **{
                k: f[k] for k in ("type", "visibility", "description", "step", "min", "max",
                                  "unique", "start") if f.get(k) not in (None, "")})
        except CounterError as e:
            flash(e.message, "error")
            return redirect(url_for("web.counter_list", ws_slug=ws_slug, new=1))
        flash(f"Counter “{c['name']}” is live.", "success")
        return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=c["name"], tab="embed"))
    q = (request.args.get("q") or "").strip().lower()
    kind = request.args.get("type") or ""
    items = [c for c in counters.list_counters(ws)
             if (not q or q in c["name"] or q in c.get("description", "").lower())
             and (not kind or c["type"] == kind)]
    return page("app/counters.html", ws, role, items=items, q=q, kind=kind,
                show_new=bool(request.args.get("new")))


@bp.route("/<ws_slug>/c/<name>")
@login_required
def counter_detail(ws_slug, name):
    ws, role = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    tab = request.args.get("tab", "overview")
    prop_filter = request.args.get("filter") or None
    ctx = dict(counter=counter, tab=tab, data=counters.serialize(counter, ws_slug),
               stats=stats.counter_stats(counter), milestones=notify.list_milestones(counter),
               referrers=stats.top_referrers(counter["_id"]),
               events=stats.event_rows(stats.recent_events([counter["_id"]], 50, prop_filter)),
               prop_filter=prop_filter or "")
    return page("app/counter.html", ws, role, **ctx)


@bp.post("/<ws_slug>/c/<name>/action")
@login_required
def counter_action(ws_slug, name):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    action = request.form.get("action")
    if action not in ("up", "down", "set", "reset"):
        abort(400, description="Unknown action.")
    try:
        res = counters.apply(ws, counter, action, by=request.form.get("by") or None,
                             value=request.form.get("value"), props={"source": "dashboard"})
    except CounterError as e:
        if request.headers.get("Accept") == "application/json":
            return jsonify(error=e.message), e.status
        flash(e.message, "error")
        return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=name))
    if request.headers.get("Accept") == "application/json":
        return jsonify(counters.serialize(res.counter, ws_slug))
    return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=name))


@bp.post("/<ws_slug>/c/<name>/settings")
@login_required
def counter_settings(ws_slug, name):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    f = request.form
    try:
        counters.update_counter(counter, {k: f.get(k) for k in
                                          ("visibility", "description", "step", "min", "max", "unique")
                                          if k in f})
        flash("Settings saved.", "success")
    except CounterError as e:
        flash(e.message, "error")
    return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=name, tab="settings"))


@bp.post("/<ws_slug>/c/<name>/delete")
@login_required
def counter_delete(ws_slug, name):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    if request.form.get("confirm") != name:
        flash("Type the counter name to confirm deletion.", "error")
        return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=name, tab="settings"))
    counters.delete_counter(counter)
    flash(f"Deleted “{name}”. That frees up a counter slot.", "success")
    return redirect(url_for("web.counter_list", ws_slug=ws_slug))


@bp.get("/<ws_slug>/c/<name>/history.json")
@login_required
def counter_history(ws_slug, name):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    try:
        return jsonify(series=stats.history(counter["_id"], request.args.get("range", "24h")))
    except stats.StatsError as e:
        abort(400, description=str(e))


@bp.get("/<ws_slug>/c/<name>/export.<fmt>")
@login_required
def counter_export(ws_slug, name, fmt):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    kind = request.args.get("kind", "events")
    if kind == "history":
        try:
            rows = stats.history(counter["_id"], request.args.get("range", "30d"))
        except stats.StatsError as e:
            abort(400, description=str(e))
        fields = ["t", "ups", "downs", "net", "events"]
    else:
        rows = stats.event_rows(stats.recent_events([counter["_id"]], 5000,
                                                    request.args.get("filter")))
        fields = stats.EVENT_FIELDS
    filename = f"{ws_slug}-{name}-{kind}.{fmt}"
    if fmt == "csv":
        resp = make_response(stats.to_csv(rows, fields))
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    elif fmt == "json":
        resp = jsonify(rows)
    else:
        abort(404)
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@bp.post("/<ws_slug>/c/<name>/milestones")
@login_required
def milestone_add(ws_slug, name):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    f = request.form
    try:
        notify.add_milestone(ws, counter, f.get("threshold"), f.get("channel"), f.get("target"),
                             user=current_user())
        flash("Milestone added.", "success")
    except notify.MilestoneError as e:
        flash(str(e), "error")
    return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=name, tab="milestones"))


@bp.post("/<ws_slug>/c/<name>/milestones/<mid>/<op>")
@login_required
def milestone_op(ws_slug, name, mid, op):
    ws, _ = workspace_or_404(ws_slug)
    counter = counter_or_404(ws, name)
    if op == "delete":
        notify.delete_milestone(counter, mid)
    elif op == "rearm":
        notify.rearm(counter, mid)
    else:
        abort(404)
    return redirect(url_for("web.counter_detail", ws_slug=ws_slug, name=name, tab="milestones"))


# ---------- tokens ----------

@bp.route("/<ws_slug>/tokens", methods=["GET", "POST"])
@login_required
def token_list(ws_slug):
    ws, role = workspace_or_404(ws_slug)
    new_token = None
    if request.method == "POST":
        owner_only(role)
        try:
            doc, new_token = tokens.create_token(ws, current_user(), request.form.get("name"),
                                                 request.form.getlist("scopes"))
        except tokens.TokenError as e:
            flash(str(e), "error")
    return page("app/tokens.html", ws, role, items=tokens.list_tokens(ws), new_token=new_token)


@bp.post("/<ws_slug>/tokens/<token_id>/revoke")
@login_required
def token_revoke(ws_slug, token_id):
    ws, role = workspace_or_404(ws_slug)
    owner_only(role)
    if tokens.revoke(ws, token_id):
        flash("Token revoked. Apps using it will stop working immediately.", "success")
    return redirect(url_for("web.token_list", ws_slug=ws_slug))


# ---------- members & settings ----------

@bp.route("/<ws_slug>/members", methods=["GET", "POST"])
@login_required
def member_list(ws_slug):
    ws, role = workspace_or_404(ws_slug)
    if request.method == "POST":
        owner_only(role)
        # Each try reveals whether a number has an account, so keep lookups slow.
        if not ratelimit.hit(f"member-add:{current_user()['_id']}", MEMBER_ADDS_PER_HOUR, 3600).allowed:
            flash("You've added a lot of people this hour. Try again later.", "error")
            return redirect(url_for("web.member_list", ws_slug=ws_slug))
        try:
            u = accounts.add_member(ws, request.form.get("phone"))
            flash(f"Added {u.get('name') or u['phone']}.", "success")
        except AccountError as e:
            flash(str(e), "error")
        return redirect(url_for("web.member_list", ws_slug=ws_slug))
    return page("app/members.html", ws, role, items=accounts.members(ws))


@bp.post("/<ws_slug>/members/<user_id>/remove")
@login_required
def member_remove(ws_slug, user_id):
    ws, role = workspace_or_404(ws_slug)
    me = current_user()
    target = accounts.get_user(user_id)
    if not target:
        abort(404)
    if target["_id"] != me["_id"]:
        owner_only(role)
    try:
        accounts.remove_member(ws, target["_id"])
    except AccountError as e:
        flash(str(e), "error")
        return redirect(url_for("web.member_list", ws_slug=ws_slug))
    if target["_id"] == me["_id"]:
        flash(f"You left “{ws_slug}”.", "success")
        return redirect(url_for("web.home"))
    return redirect(url_for("web.member_list", ws_slug=ws_slug))


@bp.route("/<ws_slug>/settings", methods=["GET", "POST"])
@login_required
def workspace_settings(ws_slug):
    ws, role = workspace_or_404(ws_slug)
    if request.method == "POST":
        owner_only(role)
        try:
            accounts.rename_workspace(ws, request.form.get("name"))
            flash("Workspace updated.", "success")
        except AccountError as e:
            flash(str(e), "error")
        return redirect(url_for("web.workspace_settings", ws_slug=ws_slug))
    return page("app/settings.html", ws, role)


@bp.post("/<ws_slug>/delete")
@login_required
def workspace_delete(ws_slug):
    ws, role = workspace_or_404(ws_slug)
    owner_only(role)
    if request.form.get("confirm") != ws_slug:
        flash("Type the workspace slug to confirm.", "error")
        return redirect(url_for("web.workspace_settings", ws_slug=ws_slug))
    accounts.delete_workspace(ws)
    flash(f"Workspace “{ws_slug}” and all its counters were deleted.", "success")
    return redirect(url_for("web.home"))


# ---------- account ----------

@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    user = current_user()
    if request.method == "POST":
        try:
            accounts.update_profile(user, request.form.get("name"))
            flash("Profile saved.", "success")
        except AccountError as e:
            flash(str(e), "error")
        return redirect(url_for("web.account"))
    return page("app/account.html")


@bp.post("/account/delete")
@login_required
def account_delete():
    user = current_user()
    if request.form.get("confirm") != "delete my account":
        flash("Type “delete my account” to confirm.", "error")
        return redirect(url_for("web.account"))
    accounts.delete_user(user)
    session.clear()
    return redirect(url_for("site.landing"))


@bp.app_context_processor
def inject():
    return {"DEMO_WS": config.DEMO_WORKSPACE, "DEMO_COUNTER": config.DEMO_COUNTER}
