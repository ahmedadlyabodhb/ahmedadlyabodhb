import os
import sqlite3
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
CORS(app, origins=["https://ahmedadlyabodhb.github.io"], supports_credentials=True)
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
        conn.commit()


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "NEXORA API"})


@app.post("/api/messages")
def create_message():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    message = str(data.get("message", "")).strip()
    if not name or not message or len(name) > 100 or len(message) > 5000:
        return jsonify({"ok": False, "error": "Invalid message."}), 400
    with db() as conn:
        conn.execute("INSERT INTO messages (name,email,message) VALUES (?,NULL,?)", (name, message))
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
    with db() as conn:
        cur = conn.execute("INSERT INTO applications (name,github,skills,why,score) VALUES (?,?,?,?,?)", (name,github,skills,why,score))
        conn.commit()
        application_id = cur.lastrowid
    return jsonify({"ok": True, "id": application_id}), 201


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
        qualified = conn.execute("SELECT COUNT(*) FROM applications WHERE score >= 80").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM applications WHERE status='accepted'").fetchone()[0]
    return jsonify({"applications": applications, "qualified": qualified, "members": members, "messages": messages})


@app.get("/api/admin/applications")
@admin_required
def admin_applications():
    with db() as conn:
        rows = conn.execute("SELECT id,name,github,skills,why,score,status,created_at FROM applications ORDER BY id DESC").fetchall()
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


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
