import os
import sqlite3
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, origins=["https://ahmedadlyabodhb.github.io", "https://ahmed-adly-portfolio.onrender.com"])
DB_PATH = os.getenv("MESSAGES_DB", "messages.db")


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.commit()


def ensure_email_optional():
    with sqlite3.connect(DB_PATH) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(messages)")]
        if "email" in columns:
            # Existing databases may still have email NOT NULL; SQLite cannot alter
            # that constraint in place, so rebuild the small messages table safely.
            info = db.execute("PRAGMA table_info(messages)").fetchall()
            email_not_null = next((row[3] for row in info if row[1] == "email"), 0)
            if email_not_null:
                db.execute("ALTER TABLE messages RENAME TO messages_old")
                db.execute(
                    """CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        email TEXT,
                        message TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                db.execute(
                    """INSERT INTO messages (id, name, email, message, created_at)
                       SELECT id, name, email, message, created_at FROM messages_old"""
                )
                db.execute("DROP TABLE messages_old")
        db.commit()


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "Ahmed Adly Portfolio API"})


@app.post("/api/messages")
def create_message():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    message = str(data.get("message", "")).strip()

    if not name or not message:
        return jsonify({"ok": False, "error": "Name and message are required."}), 400
    if len(name) > 100 or len(message) > 5000:
        return jsonify({"ok": False, "error": "Message is too long."}), 400

    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO messages (name, email, message) VALUES (?, NULL, ?)",
            (name, message),
        )
        db.commit()

    return jsonify({"ok": True, "message": "Message received."}), 201


if __name__ == "__main__":
    init_db()
    ensure_email_optional()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
else:
    init_db()
    ensure_email_optional()
