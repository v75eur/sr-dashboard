import os, json, base64, hashlib, secrets, csv, io
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, session, render_template, jsonify, Response
import requests

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", secrets.token_hex(32))

ADMIN_HASH = os.getenv("ADMIN_HASH", "d0695d2f4b6487fb81c7047ba01d06d5065aa1a9f18f89633389e1e9b5d85fd6")
GH_TOKEN   = os.getenv("GH_TOKEN", "")
GH_REPO    = os.getenv("GH_REPO", "v75eur/sr")
GH_FILE    = "users.json"
GH_ATTEMPTS_FILE = "login_attempts.json"
GH_BRANCH  = "main"
MAX_ATTEMPTS = 3
LOCK_MINUTES = 15
RESET_CODE = os.getenv("ADMIN_RESET_CODE", "rickreset1994")

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

def gh_get_attempts():
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_ATTEMPTS_FILE}?ref={GH_BRANCH}"
    r = requests.get(url, headers=gh_headers(), timeout=15)
    if r.status_code != 200:
        return {"attempts": 0, "locked_until": None}, None
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]

def gh_put_attempts(data, sha):
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_ATTEMPTS_FILE}"
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {"message": "MAJ tentatives login", "content": content, "sha": sha, "branch": GH_BRANCH}
    r = requests.put(url, headers=gh_headers(), json=payload, timeout=15)
    return r.status_code in (200, 201)

def check_locked():
    data, _ = gh_get_attempts()
    locked_until = data.get("locked_until")
    if not locked_until:
        return False, 0
    now = datetime.now()
    lock_time = datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
    if now >= lock_time:
        return False, 0
    remaining = int((lock_time - now).total_seconds() / 60) + 1
    return True, remaining

def register_fail():
    data, sha = gh_get_attempts()
    if sha is None: return
    data["attempts"] = data.get("attempts", 0) + 1
    data["last_attempt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if data["attempts"] >= MAX_ATTEMPTS:
        lock_until = datetime.now() + timedelta(minutes=LOCK_MINUTES)
        data["locked_until"] = lock_until.strftime("%Y-%m-%d %H:%M:%S")
    gh_put_attempts(data, sha)

def register_success():
    data, sha = gh_get_attempts()
    if sha is None: return
    data["attempts"] = 0
    data["locked_until"] = None
    gh_put_attempts(data, sha)

def check_login():
    return session.get("admin") is True

def compute_stats(users):
    today = datetime.now().date()
    in_7_days = today + timedelta(days=7)
    stats = {
        "total": 0, "actifs": 0, "expires": 0, "bientot": 0,
        "today_str": today.strftime("%Y-%m-%d"),
        "bientot_str": in_7_days.strftime("%Y-%m-%d")
    }
    for pseudo, info in users.items():
        stats["total"] += 1
        try:
            expire_date = datetime.strptime(info.get("expire", ""), "%Y-%m-%d").date()
        except:
            continue
        if expire_date < today:
            stats["expires"] += 1
        elif expire_date <= in_7_days:
            stats["bientot"] += 1
            stats["actifs"] += 1
        else:
            stats["actifs"] += 1
    return stats

@app.route("/")
def index():
    if check_login():
        return redirect(url_for("dashboard"))
    locked, remaining = check_locked()
    if locked:
        return render_template("login.html", error=f"🔒 Trop d'essais. Réessaie dans {remaining} min.")
    return render_template("login.html", error=None)

@app.route("/login", methods=["POST"])
def login():
    locked, remaining = check_locked()
    if locked:
        return render_template("login.html", error=f"🔒 Trop d'essais. Réessaie dans {remaining} min.")
    pwd = request.form.get("password", "")
    h = hashlib.sha256(pwd.encode()).hexdigest()
    if h == ADMIN_HASH:
        register_success()
        session["admin"] = True
        return redirect(url_for("dashboard"))
    if pwd == RESET_CODE:
        register_success()
        return render_template("login.html", error="✅ Compteur réinitialisé.")
    register_fail()
    data, _ = gh_get_attempts()
    restants = MAX_ATTEMPTS - data.get("attempts", 0)
    if restants <= 0:
        return render_template("login.html", error=f"🔒 Compte verrouillé {LOCK_MINUTES} min.")
    return render_template("login.html", error=f"Mot de passe incorrect ({restants} essai(s))")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
def dashboard():
    if not check_login():
        return redirect(url_for("index"))
    users, _ = gh_get_users()
    stats = compute_stats(users)
    return render_template("dashboard.html", users=users, stats=stats)

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
    pseudo   = (body.get("pseudo") or "").strip()
    topic    = (body.get("topic") or "").strip()
    expire   = (body.get("expire") or "").strip()
    whatsapp = (body.get("whatsapp") or "").strip()
    note     = (body.get("note") or "").strip()
    if not pseudo or not topic or not expire or not whatsapp:
        return jsonify({"error": "champs manquants"}), 400
    users, sha = gh_get_users()
    if sha is None:
        return jsonify({"error": "users.json introuvable"}), 500
    users[pseudo] = {"topic": topic, "expire": expire, "whatsapp": whatsapp, "note": note}
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

@app.route("/export.csv")
def export_csv():
    if not check_login():
        return redirect(url_for("index"))
    users, _ = gh_get_users()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Pseudo", "Topic", "Expire", "WhatsApp", "Note"])
    for pseudo, info in users.items():
        writer.writerow([
            pseudo,
            info.get("topic", ""),
            info.get("expire", ""),
            info.get("whatsapp", ""),
            info.get("note", "")
        ])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=users-{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@app.route("/ping")
def ping():
    return "ok", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
