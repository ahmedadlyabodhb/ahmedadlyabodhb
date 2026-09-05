"""Faable entrypoint for the NEXORA site.

Keep the canonical Flask application in server_v2.py while exposing the
application as server:app for hosts that automatically detect server.py.
"""

from server_v2 import app, init_db

init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "5000")))
