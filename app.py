import os, json, base64, hashlib, secrets
from flask import Flask, request, redirect, url_for, session, render_template, jsonify
import requests

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", secrets.token_hex(32))

ADMIN_HASH = os.getenv("ADMIN_HASH", "d0695d2f4b6487fb81c7047ba01d06d5065aa1a9f18f89633389e1e9b5d85fd6")
GH_TOKEN   = os.getenv("GH_TOKEN", "")
GH_REPO    = os.getenv("GH_REPO", "v75eur/sr")
GH_FILE    = "users.json"
GH_BRANCH  = "main"

def gh_headers():
    return {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

def gh_get_users():
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_FILE}?ref={GH_BRANCH}"
    r = requests.get(url, headers=gh_headers(), timeout=15)
    if r.status_code != 200:
        return {}, None
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]

def gh_put_users(users, sha, message):
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_FILE}"
    content = base64.b64encode(json.dumps(users, indent=2, ensure_ascii=False).encode()).decode()
    payload = {"message": message, "content": content, "sha": sha, "branch": GH_BRANCH}
    r = requests.put(url, headers=gh_headers(), json=payload, timeout=15)
    return r.status_code in (200, 201), r.text

def check_login():
    return session.get("admin") is True

@app.route("/")
def index():
    if check_login():
        return redirect(url_for("dashboard"))
    return render_template("login.html", error=None)

@app.route("/login", methods=["POST"])
def login():
    pwd = request.form.get("password", "")
    h = hashlib.sha256(pwd.encode()).hexdigest()
    if h == ADMIN_HASH:
        session["admin"] = True
        return redirect(url_for("dashboard"))
    return render_template("login.html", error="Mot de passe incorrect")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
def dashboard():
    if not check_login():
        return redirect(url_for("index"))
    users, _ = gh_get_users()
    return render_template("dashboard.html", users=users)

@app.route("/api/users", methods=["GET"])
def api_list():
    if not check_login():
        return jsonify({"error": "unauthorized"}), 401
    users, _ = gh_get_users()
    return jsonify(users)

@app.route("/api/users", methods=["POST"])
def api_save():
    if not check_login():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    pseudo = (body.get("pseudo") or "").strip()
    topic  = (body.get("topic") or "").strip()
    expire = (body.get("expire") or "").strip()
    note   = (body.get("note") or "").strip()
    if not pseudo or not topic or not expire:
        return jsonify({"error": "champs manquants"}), 400
    users, sha = gh_get_users()
    if sha is None:
        return jsonify({"error": "users.json introuvable"}), 500
    users[pseudo] = {"topic": topic, "expire": expire, "note": note}
    ok, msg = gh_put_users(users, sha, f"Ajout/MAJ utilisateur {pseudo}")
    if ok:
        return jsonify({"ok": True, "users": users})
    return jsonify({"error": msg}), 500

@app.route("/api/users/<pseudo>", methods=["DELETE"])
def api_delete(pseudo):
    if not check_login():
        return jsonify({"error": "unauthorized"}), 401
    users, sha = gh_get_users()
    if sha is None:
        return jsonify({"error": "users.json introuvable"}), 500
    if pseudo not in users:
        return jsonify({"error": "utilisateur introuvable"}), 404
    del users[pseudo]
    ok, msg = gh_put_users(users, sha, f"Suppression utilisateur {pseudo}")
    if ok:
        return jsonify({"ok": True, "users": users})
    return jsonify({"error": msg}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
