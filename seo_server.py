from pathlib import Path
import json

from flask import Response

from server_v2 import app, BASE_DIR

SITE_URL = "https://ahmedadlyabodhb-wvyxf.faable.link/"

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


def _seo_home():
    path = Path(BASE_DIR) / "index.html"
    html = path.read_text(encoding="utf-8")

    # Keep the existing design/content, while making the main document stronger for search.
    html = html.replace('<meta name="description" content="Ahmed Adly — Python Developer Portfolio">',
                        '<meta name="description" content="Ahmed Adly (أحمد عدلي) — Python Developer Portfolio, software projects, skills, services and NEXORA.">')
    html = html.replace('<title>Ahmed Adly — Python Developer</title>',
                        '<title>Ahmed Adly (أحمد عدلي) — Python Developer</title>')
    html = html.replace('</head>', SEO_HEAD + '</head>', 1)

    # Use clean canonical page URLs in the homepage navigation.
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


# server_v2 already owns the homepage route; replace only its view function so
# every normal request gets the SEO-enhanced document without changing the app's APIs.
app.view_functions["home"] = _seo_home
