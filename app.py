import re

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import db

app = Flask(__name__)
db.init()

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def check(*parts):
    for p in parts:
        if not SLUG.match(p):
            abort(400, description="Names must be 1-64 chars: lowercase letters, digits, - or _")


@app.after_request
def cors(resp):
    # Counters are meant to be hit from any website.
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(400)
@app.errorhandler(404)
def error(e):
    if request.path.startswith("/api/"):
        return jsonify(error=e.description), e.code
    return render_template("error.html", error=e), e.code


# ---------- API ----------

@app.get("/api/v1/<namespace>/<name>")
def api_get(namespace, name):
    check(namespace, name)
    row = db.get(namespace, name)
    if not row:
        abort(404, description="Counter not found")
    return jsonify(namespace=namespace, name=name, count=row[0])


@app.get("/api/v1/<namespace>/<name>/up")
def api_up(namespace, name):
    check(namespace, name)
    return jsonify(namespace=namespace, name=name, count=db.add(namespace, name, 1))


@app.get("/api/v1/<namespace>/<name>/down")
def api_down(namespace, name):
    check(namespace, name)
    return jsonify(namespace=namespace, name=name, count=db.add(namespace, name, -1))


# ---------- Frontend ----------

@app.get("/")
def home():
    return render_template("index.html")


@app.post("/jar")
def open_jar():
    namespace = request.form.get("namespace", "").strip().lower()
    check(namespace)
    return redirect(url_for("jar", namespace=namespace))


@app.get("/jar/<namespace>")
def jar(namespace):
    check(namespace)
    return render_template("jar.html", namespace=namespace, counters=db.list_namespace(namespace))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
