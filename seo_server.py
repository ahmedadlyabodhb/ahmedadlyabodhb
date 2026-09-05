from pathlib import Path
import hmac
import os
from collections import defaultdict, deque
from time import monotonic

from flask import Response, jsonify, request, session

from server_v2 import app, BASE_DIR

SITE_URL = "https://ahmedadlyabodhb-wvyxf.faable.link/"


def _adsense_head():
    publisher_id = os.getenv("ADSENSE_PUBLISHER_ID", "").strip()
    if not publisher_id or not publisher_id.startswith("ca-pub-"):
        return ""
    return f'''\n<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={publisher_id}" crossorigin="anonymous"></script>\n<meta name="google-adsense-account" content="{publisher_id}">\n'''


SEO_HEAD = '''
<meta name="author" content="Ahmed Adly (أحمد عدلي)">
<meta name="keywords" content="أحمد عدلي, Ahmed Adly, أحمد عدلي Python Developer, Python Developer, Software Developer">
<meta name="robots" content="index,follow">
<link rel="canonical" href="https://ahmedadlyabodhb-wvyxf.faable.link/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Ahmed Adly">
<meta property="og:title" content="Ahmed Adly (أحمد عدلي) — Python Developer">
<meta property="og:description" content="Ahmed Adly (أحمد عدلي) — Python Developer Portfolio and NEXORA.">
<meta property="og:url" content="https://ahmedadlyabodhb-wvyxf.faable.link/">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="Ahmed Adly (أحمد عدلي) — Python Developer">
<meta name="twitter:description" content="Ahmed Adly (أحمد عدلي) — Python Developer Portfolio and NEXORA.">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Ahmed Adly",
  "alternateName": "أحمد عدلي",
  "url": "https://ahmedadlyabodhb-wvyxf.faable.link/",
  "jobTitle": "Python Developer",
  "sameAs": ["https://github.com/ahmedadlyabodhb"]
}
</script>
'''


@app.get("/ads.txt")
def ads_txt():
    publisher_id = os.getenv("ADSENSE_PUBLISHER_ID", "").strip()
    if not publisher_id.startswith("ca-pub-"):
        return Response("", status=404, mimetype="text/plain")
    pub_number = publisher_id.removeprefix("ca-pub-")
    return Response(
        f"google.com, pub-{pub_number}, DIRECT, f08c47fec0942fa0\n",
        mimetype="text/plain",
    )


# Keep admin login compatible with the common Render environment-variable names.
# Credentials are still read only from server environment variables; nothing is hard-coded.
_admin_attempts = defaultdict(deque)
_ADMIN_WINDOW = 600
_ADMIN_LIMIT = 5


def _admin_login():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    now = monotonic()
    attempts = _admin_attempts[ip]
    while attempts and now - attempts[0] > _ADMIN_WINDOW:
        attempts.popleft()
    if len(attempts) >= _ADMIN_LIMIT:
        return jsonify({"ok": False, "error": "Too many login attempts. Try again later."}), 429

    expected_user = (os.getenv("ADMIN_USERNAME") or os.getenv("ADMIN_USER") or "").strip()
    expected_pass = os.getenv("ADMIN_PASSWORD") or os.getenv("ADMIN_PASS") or ""
    data = request.get_json(silent=True) or {}
    supplied_user = str(data.get("username", "")).strip()
    supplied_pass = str(data.get("password", ""))

    if not expected_user or not expected_pass:
        return jsonify({"ok": False, "error": "Admin credentials are not configured on the server."}), 503

    if not hmac.compare_digest(supplied_user, expected_user) or not hmac.compare_digest(supplied_pass, expected_pass):
        attempts.append(now)
        return jsonify({"ok": False, "error": "Invalid credentials."}), 401

    _admin_attempts.pop(ip, None)
    session.clear()
    session["admin"] = True
    return jsonify({"ok": True})


# Replace server_v2's login view while leaving all existing API/dashboard routes intact.
app.view_functions["admin_login"] = _admin_login


def _seo_home():
    path = Path(BASE_DIR) / "index.html"
    html = path.read_text(encoding="utf-8")
    html = html.replace(
        '<meta name="description" content="Ahmed Adly — Python Developer Portfolio">',
        '<meta name="description" content="Ahmed Adly (أحمد عدلي) — Python Developer Portfolio, software projects, skills, services and NEXORA.">',
    )
    html = html.replace(
        '<title>Ahmed Adly — Python Developer</title>',
        '<title>Ahmed Adly (أحمد عدلي) — Python Developer</title>',
    )
    html = html.replace('</head>', SEO_HEAD + _adsense_head() + '</head>', 1)
    replacements = {
        'href="team.html"': 'href="/team"',
        'href="challenge.html"': 'href="/challenge"',
        'href="join.html"': 'href="/join"',
        'href="application-status.html"': 'href="/application-status"',
        'href="admin.html"': 'href="/admin"',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return Response(html, mimetype="text/html")


app.view_functions["home"] = _seo_home
