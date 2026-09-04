import os
import re
import secrets
import sqlite3
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path
from time import monotonic

from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("MESSAGES_DB", str(BASE_DIR / "messages.db"))

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
app.config.update(
    SECRET_KEY=os.environ.get("APP_SECRET", "change-this-before-production"),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=64 * 1024,
)

allowed_origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "").split(",") if x.strip()]
if allowed_origins:
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

login_attempts = defaultdict(deque)
LOGIN_WINDOW = 600
LOGIN_LIMIT = 5

DEFAULT_SETTINGS = {
    "site_title": "Ahmed Adly — Python Developer",
    "site_status": "online",
    "nexora_enabled": "true",
    "contact_enabled": "true",
    "maintenance_message": "",
}


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def clean_username(value):
    return str(value or "").strip().lstrip("@").lower()


def valid_username(value):
    return bool(re.fullmatch(r"[a-z0-9_-]{3,40}", value or ""))


def username_taken(conn, username, exclude_member_id=None, application_id=None):
    app_row = conn.execute(
        "SELECT id FROM applications WHERE username=? AND (? IS NULL OR id != ?)",
        (username, application_id, application_id),
    ).fetchone()
    if app_row:
        return True
    member_sql = "SELECT id FROM members WHERE username=?"
    params = [username]
    if exclude_member_id is not None:
        member_sql += " AND id != ?"
        params.append(exclude_member_id)
    member_row = conn.execute(member_sql, params).fetchone()
    return bool(member_row)


def unique_member_username(requested, conn, application_id=None, exclude_member_id=None):
    username = clean_username(requested)
    if not valid_username(username):
        username = re.sub(r"[^a-z0-9_-]+", "_", username)[:40].strip("_") or "member"
    username = username[:40]
    if not username_taken(conn, username, exclude_member_id=exclude_member_id, application_id=application_id):
        return username
    base = username
    for n in range(2, 1000):
        suffix = f"_{n}"
        candidate = base[:40 - len(suffix)] + suffix
        if not username_taken(conn, candidate, exclude_member_id=exclude_member_id, application_id=application_id):
            return candidate
    return f"member_{secrets.token_hex(4)}"[:40]


def make_username(name, conn):
    base = re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")[:30] or "applicant"
    return unique_member_username(base, conn)


def make_status_token():
    return secrets.token_urlsafe(24)


def init_db():
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,username TEXT,github TEXT,skills TEXT NOT NULL,why TEXT NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',status_token TEXT UNIQUE,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS members (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,username TEXT NOT NULL UNIQUE,github TEXT,skills TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'NEXORA Member',bio TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,application_id INTEGER UNIQUE,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))

        cols = {row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
        if "username" not in cols:
            conn.execute("ALTER TABLE applications ADD COLUMN username TEXT")
        if "status_token" not in cols:
            conn.execute("ALTER TABLE applications ADD COLUMN status_token TEXT")

        old = conn.execute("SELECT id,name FROM applications WHERE username IS NULL OR username='' ORDER BY id").fetchall()
        for row in old:
            conn.execute("UPDATE applications SET username=? WHERE id=?", (make_username(row["name"], conn), row["id"]))

        rows = conn.execute("SELECT id FROM applications WHERE status_token IS NULL OR status_token='' ").fetchall()
        for row in rows:
            conn.execute("UPDATE applications SET status_token=? WHERE id=?", (make_status_token(), row[0]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_status_token ON applications(status_token)")

        accepted = conn.execute("SELECT id,name,username,github,skills FROM applications WHERE status='accepted'").fetchall()
        for row in accepted:
            existing = conn.execute("SELECT id FROM members WHERE application_id=?", (row["id"],)).fetchone()
            if not existing:
                username = unique_member_username(row["username"] or row["name"], conn, application_id=row["id"])
                conn.execute(
                    "INSERT INTO members(name,username,github,skills,role,bio,active,application_id) VALUES(?,?,?,?,?,?,1,?)",
                    (row["name"], username, row["github"] or "", row["skills"], "NEXORA Member", "", row["id"]),
                )
        conn.commit()


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


def client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def login_rate_limited(ip):
    now = monotonic()
    q = login_attempts[ip]
    while q and now - q[0] > LOGIN_WINDOW:
        q.popleft()
    return len(q) >= LOGIN_LIMIT


def mark_login_failure(ip):
    login_attempts[ip].append(monotonic())


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.get("/")
@app.get("/index.html")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/team")
@app.get("/team/")
@app.get("/team.html")
def team_page():
    return send_from_directory(BASE_DIR, "team.html")


@app.get("/challenge")
@app.get("/challenge/")
@app.get("/challenge.html")
def challenge_page():
    return send_from_directory(BASE_DIR, "challenge.html")


@app.get("/join")
@app.get("/join/")
@app.get("/join.html")
def join_page():
    return send_from_directory(BASE_DIR, "join.html")


@app.get("/application-status")
@app.get("/application-status/")
@app.get("/application-status.html")
def application_status_page():
    return send_from_directory(BASE_DIR, "application-status.html")


@app.get("/admin")
@app.get("/admin/")
@app.get("/admin.html")
def admin_page():
    return send_from_directory(BASE_DIR, "admin.html")


@app.get("/health")
@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "NEXORA API", "database": os.path.basename(DB_PATH)})


@app.get("/api/site-config")
def site_config():
    with db() as conn:
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
    return jsonify({"ok": True, "settings": {row["key"]: row["value"] for row in rows}})


@app.get("/api/members")
def public_members():
    with db() as conn:
        rows = conn.execute("SELECT id,name,username,github,skills,role,bio FROM members WHERE active=1 ORDER BY id").fetchall()
    return jsonify({"ok": True, "members": [dict(row) for row in rows]})


@app.post("/api/messages")
def create_message():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip()
    message = str(data.get("message", "")).strip()
    if not name or not message or len(name) > 100 or len(email) > 200 or len(message) > 5000:
        return jsonify({"ok": False, "error": "Invalid message."}), 400
    with db() as conn:
        conn.execute("INSERT INTO messages(name,email,message) VALUES(?,?,?)", (name, email or None, message))
        conn.commit()
    return jsonify({"ok": True}), 201


@app.post("/api/applications")
def create_application():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    username = clean_username(data.get("username"))
    github = str(data.get("github", "")).strip()
    skills = str(data.get("skills", "")).strip()
    why = str(data.get("why", "")).strip()
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    if score < 80 or not name or not username or not skills or not why:
        return jsonify({"ok": False, "error": "Name, username, skills and a qualified score are required."}), 400
    if len(name) > 100 or len(username) > 40 or len(github) > 200 or len(skills) > 300 or len(why) > 3000:
        return jsonify({"ok": False, "error": "Application is too long."}), 400
    if not valid_username(username):
        return jsonify({"ok": False, "error": "Username can use letters, numbers, underscore and hyphen only."}), 400

    with db() as conn:
        if username_taken(conn, username):
            return jsonify({"ok": False, "error": "That username is already in use. Please choose another username."}), 409
        status_token = make_status_token()
        cur = conn.execute(
            "INSERT INTO applications(name,username,github,skills,why,score,status_token) VALUES(?,?,?,?,?,?,?)",
            (name, username, github, skills, why, score, status_token),
        )
        conn.commit()
        application_id = cur.lastrowid
    return jsonify({"ok": True, "id": application_id, "username": username}), 201


@app.get("/api/applications/status/<username>")
def application_status(username):
    username = clean_username(username)
    if not valid_username(username):
        return jsonify({"ok": False, "error": "Invalid username."}), 400
    with db() as conn:
        row = conn.execute(
            "SELECT name,username,score,status,created_at FROM applications WHERE username=? ORDER BY id DESC LIMIT 1",
            (username,),
        ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Application not found for this username."}), 404
    return jsonify({"ok": True, **dict(row)})


@app.post("/api/admin/login")
def admin_login():
    ip = client_ip()
    if login_rate_limited(ip):
        return jsonify({"ok": False, "error": "Too many login attempts. Try again later."}), 429
    expected_user = os.getenv("ADMIN_USERNAME")
    expected_pass = os.getenv("ADMIN_PASSWORD")
    data = request.get_json(silent=True) or {}
    if not expected_user or not expected_pass:
        return jsonify({"ok": False, "error": "Admin credentials are not configured on the server."}), 503
    if data.get("username") != expected_user or data.get("password") != expected_pass:
        mark_login_failure(ip)
        return jsonify({"ok": False, "error": "Invalid credentials."}), 401
    login_attempts.pop(ip, None)
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
        qualified = conn.execute("SELECT COUNT(*) FROM applications WHERE score>=80").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM members WHERE active=1").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM applications WHERE status='rejected'").fetchone()[0]
    return jsonify({"applications": applications, "pending": pending, "qualified": qualified, "members": members, "rejected": rejected, "messages": messages})


@app.get("/api/admin/applications")
@admin_required
def admin_applications():
    with db() as conn:
        rows = conn.execute("SELECT id,name,username,github,skills,why,score,status,created_at FROM applications ORDER BY id DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.patch("/api/admin/applications/<int:application_id>")
@admin_required
def update_application(application_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in {"pending", "accepted", "rejected"}:
        return jsonify({"ok": False, "error": "Invalid status."}), 400
    with db() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Application not found."}), 404
        conn.execute("UPDATE applications SET status=? WHERE id=?", (status, application_id))
        if status == "accepted":
            member = conn.execute("SELECT id FROM members WHERE application_id=?", (application_id,)).fetchone()
            if member:
                conn.execute("UPDATE members SET active=1,updated_at=CURRENT_TIMESTAMP WHERE application_id=?", (application_id,))
            else:
                username = unique_member_username(row["username"] or row["name"], conn, application_id=application_id)
                conn.execute(
                    "INSERT INTO members(name,username,github,skills,role,bio,active,application_id) VALUES(?,?,?,?,?,?,1,?)",
                    (row["name"], username, row["github"] or "", row["skills"], "NEXORA Member", "", application_id),
                )
        else:
            conn.execute("UPDATE members SET active=0,updated_at=CURRENT_TIMESTAMP WHERE application_id=?", (application_id,))
        conn.commit()
    return jsonify({"ok": True})


@app.delete("/api/admin/applications/<int:application_id>")
@admin_required
def delete_application(application_id):
    with db() as conn:
        conn.execute("DELETE FROM members WHERE application_id=?", (application_id,))
        cur = conn.execute("DELETE FROM applications WHERE id=?", (application_id,))
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"ok": False, "error": "Application not found."}), 404
    return jsonify({"ok": True})


@app.get("/api/admin/messages")
@admin_required
def admin_messages():
    with db() as conn:
        rows = conn.execute("SELECT id,name,email,message,created_at FROM messages ORDER BY id DESC").fetchall()
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


@app.get("/api/admin/members")
@admin_required
def admin_members():
    with db() as conn:
        rows = conn.execute("SELECT id,name,username,github,skills,role,bio,active,application_id,created_at,updated_at FROM members ORDER BY id DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.patch("/api/admin/members/<int:member_id>")
@admin_required
def update_member(member_id):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    username = clean_username(data.get("username"))
    github = str(data.get("github", "")).strip()
    skills = str(data.get("skills", "")).strip()
    role = str(data.get("role", "NEXORA Member")).strip() or "NEXORA Member"
    bio = str(data.get("bio", "")).strip()
    active = 1 if bool(data.get("active", True)) else 0

    if not name or not skills or len(name) > 100 or len(username) > 40 or len(github) > 200 or len(skills) > 300 or len(role) > 100 or len(bio) > 1000:
        return jsonify({"ok": False, "error": "Invalid member data."}), 400
    if not valid_username(username):
        return jsonify({"ok": False, "error": "Invalid username."}), 400

    with db() as conn:
        row = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Member not found."}), 404
        if username != row["username"] and username_taken(conn, username, exclude_member_id=member_id):
            return jsonify({"ok": False, "error": "That username is already in use."}), 409
        conn.execute(
            "UPDATE members SET name=?,username=?,github=?,skills=?,role=?,bio=?,active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, username, github, skills, role, bio, active, member_id),
        )
        conn.commit()
    return jsonify({"ok": True})


@app.delete("/api/admin/members/<int:member_id>")
@admin_required
def delete_member(member_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM members WHERE id=?", (member_id,))
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"ok": False, "error": "Member not found."}), 404
    return jsonify({"ok": True})


@app.patch("/api/admin/site-config")
@admin_required
def update_site_config():
    data = request.get_json(silent=True) or {}
    allowed = set(DEFAULT_SETTINGS)
    with db() as conn:
        for key, value in data.items():
            if key not in allowed:
                continue
            value = str(value)[:500]
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()
    return site_config()


@app.get("/<path:filename>")
def public_file(filename):
    target = (BASE_DIR / filename).resolve()
    if target.is_file() and (target == BASE_DIR or BASE_DIR in target.parents):
        return send_from_directory(BASE_DIR, filename)
    return jsonify({"ok": False, "error": "Page not found."}), 404


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
