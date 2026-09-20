import os, json, base64, hashlib, secrets
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, session, render_template, jsonify
import requests

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", secrets.token_hex(32))

ADMIN_HASH = os.getenv("ADMIN_HASH", "d0695d2f4b6487fb81c7047ba01d06d5065aa1a9f18f89633389e1e9b5d85fd6")
GH_TOKEN   = os.getenv("GH_TOKEN", "")
GH_REPO    = os.getenv("GH_REPO", "v75eur/sr")
GH_FILE    = "users.json"
GH_MSG_FILE = "messages.json"
GH_ATTEMPTS_FILE = "login_attempts.json"
GH_BRANCH  = "main"
MAX_MSG_PER_USER = 12
MAX_ATTEMPTS = 3
LOCK_MINUTES = 15
RESET_CODE = os.getenv("ADMIN_RESET_CODE", "rickreset1994")

def gh_headers():
    return {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

# ---------- USERS ----------
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

# ---------- MESSAGES ----------
def gh_get_messages():
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_MSG_FILE}?ref={GH_BRANCH}"
    r = requests.get(url, headers=gh_headers(), timeout=15)
    if r.status_code != 200:
        return {}, None
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]

def gh_put_messages(msgs, sha, message):
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_MSG_FILE}"
    content = base64.b64encode(json.dumps(msgs, indent=2, ensure_ascii=False).encode()).decode()
    payload = {"message": message, "content": content, "sha": sha, "branch": GH_BRANCH}
    r = requests.put(url, headers=gh_headers(), json=payload, timeout=15)
    return r.status_code in (200, 201), r.text

# ---------- LOGIN ATTEMPTS ----------
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

# ---------- ROUTES ----------
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
        return render_template("login.html", error="✅ Compteur réinitialisé. Tu peux te reconnecter.")
    register_fail()
    data, _ = gh_get_attempts()
    restants = MAX_ATTEMPTS - data.get("attempts", 0)
    if restants <= 0:
        return render_template("login.html", error=f"🔒 Compte verrouillé {LOCK_MINUTES} min.")
    return render_template("login.html", error=f"Mot de passe incorrect ({restants} essai(s) restant(s))")

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
    pseudo   = (body.get("pseudo") or "").strip()
    topic    = (body.get("topic") or "").strip()
    expire   = (body.get("expire") or "").strip()
    whatsapp = (body.get("whatsapp") or "").strip()
    note     = (body.get("note") or "").strip()
    if not pseudo or not topic or not expire or not whatsapp:
        return jsonify({"error": "champs manquants (pseudo, topic, expire, whatsapp)"}), 400
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

@app.route("/messages")
def messages_page():
    if not check_login():
        return redirect(url_for("index"))
    msgs, _ = gh_get_messages()
    users, _ = gh_get_users()
    return render_template("messages.html", messages=msgs, users=users)

@app.route("/contact")
def contact_page():
    users, _ = gh_get_users()
    today = datetime.now().strftime("%Y-%m-%d")
    actifs = {p: i for p, i in users.items() if i.get("expire", "") >= today}
    return render_template("contact.html", users=actifs)

@app.route("/api/messages", methods=["POST"])
def api_send_message():
    body = request.get_json() or {}
    pseudo = (body.get("pseudo") or "").strip()
    texte  = (body.get("texte") or "").strip()
    if not pseudo or not texte:
        return jsonify({"error": "pseudo et message requis"}), 400
    if len(texte) > 1000:
        return jsonify({"error": "message trop long (max 1000)"}), 400
    msgs, sha = gh_get_messages()
    if sha is None:
        return jsonify({"error": "messages.json introuvable"}), 500
    if pseudo not in msgs:
        msgs[pseudo] = []
    msgs[pseudo].append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "from": "user",
        "texte": texte
    })
    msgs[pseudo] = msgs[pseudo][-MAX_MSG_PER_USER:]
    ok, msg = gh_put_messages(msgs, sha, f"Message de {pseudo}")
    if ok:
        try:
            requests.post("https://ntfy.sh/admin-sr",
                data=f"Nouveau message de {pseudo}: {texte}".encode(),
                headers={"Title": "Nouveau message"}, timeout=10)
        except: pass
        return jsonify({"ok": True})
    return jsonify({"error": msg}), 500

@app.route("/api/reply", methods=["POST"])
def api_reply():
    if not check_login():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    pseudo = (body.get("pseudo") or "").strip()
    texte  = (body.get("texte") or "").strip()
    if not pseudo or not texte:
        return jsonify({"error": "pseudo et message requis"}), 400
    users, _ = gh_get_users()
    if pseudo not in users:
        return jsonify({"error": "utilisateur introuvable"}), 404
    topic = users[pseudo].get("topic", "")
    full_url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic}"
    try:
        requests.post(full_url, data=texte.encode(),
            headers={"Title": "Message de l'admin"}, timeout=15)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    msgs, sha = gh_get_messages()
    if sha is not None:
        if pseudo not in msgs:
            msgs[pseudo] = []
        msgs[pseudo].append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "from": "admin",
            "texte": texte
        })
        msgs[pseudo] = msgs[pseudo][-MAX_MSG_PER_USER:]
        gh_put_messages(msgs, sha, f"Réponse à {pseudo}")
    return jsonify({"ok": True})

@app.route("/broadcast")
def broadcast_page():
    if not check_login():
        return redirect(url_for("index"))
    users, _ = gh_get_users()
    return render_template("broadcast.html", users=users)

@app.route("/api/broadcast", methods=["POST"])
def api_broadcast():
    if not check_login():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json() or {}
    title   = (body.get("title") or "").strip()
    message = (body.get("message") or "").strip()
    target  = (body.get("target") or "all").strip()
    if not title or not message:
        return jsonify({"error": "titre et message requis"}), 400
    users, _ = gh_get_users()
    today = datetime.now().strftime("%Y-%m-%d")
    if target == "all":
        cibles = [(p, i) for p, i in users.items() if i.get("expire", "") >= today and i.get("topic")]
    else:
        if target not in users:
            return jsonify({"error": "utilisateur introuvable"}), 404
        cibles = [(target, users[target])]
    resultats = []
    for pseudo, info in cibles:
        topic = info.get("topic", "")
        full_url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic}"
        try:
            r = requests.post(full_url,
                data=message.encode("utf-8"),
                headers={"Title": title.encode("utf-8")}, timeout=15)
            resultats.append({"pseudo": pseudo, "status": r.status_code})
        except Exception as e:
            resultats.append({"pseudo": pseudo, "error": str(e)})
    return jsonify({"ok": True, "resultats": resultats})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
