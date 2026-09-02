import os
import sqlite3
import secrets
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("APP_SECRET", "change-this-before-production"),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="None",
)

# The public site may be served from GitHub Pages or the Faable deployment.
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
DB_PATH = os.getenv("MESSAGES_DB", "messages.db")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            github TEXT,
            skills TEXT NOT NULL,
            why TEXT NOT NULL,
            score INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        defaults = {
            "site_title": "Ahmed Adly — Python Developer",
            "site_status": "online",
            "nexora_enabled": "true",
            "contact_enabled": "true",
            "maintenance_message": "",
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
        if "status_token" not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN status_token TEXT")
        rows = conn.execute("SELECT id FROM applications WHERE status_token IS NULL OR status_token='' ").fetchall()
        for row in rows:
            conn.execute("UPDATE applications SET status_token=? WHERE id=?", (secrets.token_urlsafe(24), row[0]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_status_token ON applications(status_token)")
        conn.commit()


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.get("/")
@app.get("/index.html")
def home():
    return send_from_directory(".", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "NEXORA API", "database": os.path.basename(DB_PATH)})


@app.get("/api/site-config")
def site_config():
    with db() as conn:
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
    return jsonify({"ok": True, "settings": {row["key"]: row["value"] for row in rows}})


@app.post("/api/messages")
def create_message():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    message = str(data.get("message", "")).strip()
    if not name or not message or len(name) > 100 or len(email) > 200 or len(message) > 5000:
        return jsonify({"ok": False, "error": "Invalid message."}), 400
    with db() as conn:
        conn.execute("INSERT INTO messages (name,email,message) VALUES (?,?,?)", (name, email or None, message))
        conn.commit()
    return jsonify({"ok": True}), 201


@app.post("/api/applications")
def create_application():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    github = str(data.get("github", "")).strip()
    skills = str(data.get("skills", "")).strip()
    why = str(data.get("why", "")).strip()
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    if score < 80 or not name or not skills or not why:
        return jsonify({"ok": False, "error": "A valid qualified application is required."}), 400
    if len(name) > 100 or len(github) > 200 or len(skills) > 300 or len(why) > 3000:
        return jsonify({"ok": False, "error": "Application is too long."}), 400
    status_token = secrets.token_urlsafe(24)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO applications (name,github,skills,why,score,status_token) VALUES (?,?,?,?,?,?)",
            (name, github, skills, why, score, status_token),
        )
        conn.commit()
        application_id = cur.lastrowid
    return jsonify({"ok": True, "id": application_id, "status_token": status_token}), 201


@app.get("/api/applications/status/<status_token>")
def application_status(status_token):
    with db() as conn:
        row = conn.execute(
            "SELECT name,score,status,created_at FROM applications WHERE status_token=?",
            (status_token,),
        ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Application not found."}), 404
    return jsonify({
        "ok": True,
        "name": row["name"],
        "score": row["score"],
        "status": row["status"],
        "created_at": row["created_at"],
    })


@app.post("/api/admin/login")
def admin_login():
    expected_user = os.getenv("ADMIN_USERNAME")
    expected_pass = os.getenv("ADMIN_PASSWORD")
    data = request.get_json(silent=True) or {}
    if not expected_user or not expected_pass:
        return jsonify({"ok": False, "error": "Admin credentials are not configured on the server."}), 503
    if data.get("username") != expected_user or data.get("password") != expected_pass:
        return jsonify({"ok": False, "error": "Invalid credentials."}), 401
    session.clear()
    session["admin"] = True
    return jsonify({"ok": True})


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/admin/summary")
@admin_required
def admin_summary():
    with db() as conn:
        applications = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM applications WHERE status='pending'").fetchone()[0]
        qualified = conn.execute("SELECT COUNT(*) FROM applications WHERE score >= 80").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM applications WHERE status='accepted'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM applications WHERE status='rejected'").fetchone()[0]
    return jsonify({
        "applications": applications,
        "pending": pending,
        "qualified": qualified,
        "members": members,
        "rejected": rejected,
        "messages": messages,
    })


@app.get("/api/admin/applications")
@admin_required
def admin_applications():
    with db() as conn:
        rows = conn.execute(
            "SELECT id,name,github,skills,why,score,status,created_at FROM applications ORDER BY id DESC"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.patch("/api/admin/applications/<int:application_id>")
@admin_required
def update_application(application_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"pending", "accepted", "rejected"}:
        return jsonify({"ok": False, "error": "Invalid status."}), 400
    with db() as conn:
        cur = conn.execute("UPDATE applications SET status=? WHERE id=?", (status, application_id))
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"ok": False, "error": "Application not found."}), 404
    return jsonify({"ok": True})


@app.delete("/api/admin/applications/<int:application_id>")
@admin_required
def delete_application(application_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM applications WHERE id=?", (application_id,))
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"ok": False, "error": "Application not found."}), 404
    return jsonify({"ok": True})


@app.get("/api/admin/messages")
@admin_required
def admin_messages():
    with db() as conn:
        rows = conn.execute(
            "SELECT id,name,email,message,created_at FROM messages ORDER BY id DESC"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.delete("/api/admin/messages/<int:message_id>")
@admin_required
def delete_message(message_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM messages WHERE id=?", (message_id,))
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"ok": False, "error": "Message not found."}), 404
    return jsonify({"ok": True})


@app.get("/api/admin/site-config")
@admin_required
def admin_site_config():
    return site_config()


@app.patch("/api/admin/site-config")
@admin_required
def update_site_config():
    data = request.get_json(silent=True) or {}
    allowed = {"site_title", "site_status", "nexora_enabled", "contact_enabled", "maintenance_message"}
    clean = {k: str(v).strip() for k, v in data.items() if k in allowed}
    if clean.get("site_status") not in {None, "online", "maintenance"}:
        return jsonify({"ok": False, "error": "Invalid site status."}), 400
    for key in ("nexora_enabled", "contact_enabled"):
        if key in clean and clean[key] not in {"true", "false"}:
            return jsonify({"ok": False, "error": "Invalid setting value."}), 400
    with db() as conn:
        for key, value in clean.items():
            conn.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()
    return site_config()


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
