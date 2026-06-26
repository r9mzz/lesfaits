import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
articles = json.loads((DATA / "articles.json").read_text(encoding="utf-8"))

base   = "https://r9mzz.github.io/lesfaits"
today  = datetime.now().strftime("%Y-%m-%d")

urls = []

# Pages statiques principales
static = [
    ("", "1.0", "daily"),
    ("methode.html", "0.7", "monthly"),
    ("contact.html", "0.5", "monthly"),
    ("corrections.html", "0.6", "weekly"),
    ("archive.html", "0.8", "weekly"),
    ("mentions-legales.html", "0.3", "yearly"),
    ("confidentialite.html", "0.3", "yearly"),
    ("cgu.html", "0.3", "yearly"),
    ("feed.xml", "0.4", "daily"),
]
for path, priority, freq in static:
    loc = f"{base}/{path}" if path else f"{base}/"
    urls.append(f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>{freq}</changefreq>\n    <priority>{priority}</priority>\n  </url>")

# Pages catégories
for cat in ["societe", "science", "economie", "tech", "sante", "environnement"]:
    urls.append(f"  <url>\n    <loc>{base}/categories/{cat}.html</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>")

# Articles
for a in articles:
    urls.append(f"  <url>\n    <loc>{base}/articles/{a['slug']}.html</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.9</priority>\n  </url>")

xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>"
(ROOT / "sitemap.xml").write_text(xml, encoding="utf-8")
print(f"sitemap.xml généré — {len(urls)} URLs")
