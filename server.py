"""Faable entrypoint for the NEXORA site."""
import hmac
import os

from flask import jsonify, request, session

from server_v2 import app, client_ip, init_db, login_attempts, login_rate_limited, mark_login_failure

init_db()


def faable_admin_login():
    ip = client_ip()
    if login_rate_limited(ip):
        return jsonify({"ok": False, "error": "Too many login attempts. Try again later."}), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = request.form.to_dict()
    expected_user = os.getenv("ADMIN_USERNAME") or os.getenv("ADMIN_USER")
    expected_pass = os.getenv("ADMIN_PASSWORD") or os.getenv("ADMIN_PASS")
    if not expected_user or not expected_pass:
        return jsonify({"ok": False, "error": "Admin credentials are not configured on the server."}), 503
    supplied_user = str(data.get("username", "")).strip()
    supplied_pass = str(data.get("password", ""))
    user_ok = hmac.compare_digest(supplied_user.casefold(), str(expected_user).strip().casefold())
    pass_ok = hmac.compare_digest(supplied_pass, str(expected_pass))
    if not (user_ok and pass_ok):
        mark_login_failure(ip)
        return jsonify({"ok": False, "error": "Invalid credentials."}), 401
    login_attempts.pop(ip, None)
    session.clear()
    session.permanent = True
    session["admin"] = True
    return jsonify({"ok": True})

app.view_functions["admin_login"] = faable_admin_login

@app.get("/admin")
@app.get("/admin/")
def admin_page():
    return app.send_static_file("admin-new.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
