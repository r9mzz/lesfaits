import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
articles = json.loads((DATA / "articles.json").read_text(encoding="utf-8"))

base = "https://r9mzz.github.io/lesfaits"
now = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

def escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

items = []
for a in articles[:20]:
    slug   = a["slug"]
    titre  = escape(a["titre"])
    resume = escape(" ".join(a["resume"]) if isinstance(a.get("resume"), list) else a.get("resume", ""))
    cat    = escape(a.get("categorie", ""))
    url    = f"{base}/articles/{slug}.html"
    img    = f"{base}/assets/images/{slug}.jpg"
    items.append(
        f"  <item>\n"
        f"    <title>{titre}</title>\n"
        f"    <link>{url}</link>\n"
        f"    <guid isPermaLink=\"true\">{url}</guid>\n"
        f"    <description>{resume}</description>\n"
        f"    <category>{cat}</category>\n"
        f"    <enclosure url=\"{img}\" type=\"image/jpeg\" length=\"0\"/>\n"
        f"    <pubDate>{now}</pubDate>\n"
        f"  </item>"
    )

xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>Les Faits</title>
  <link>{base}/</link>
  <description>Journal numérique français rédigé par IA. Juste les faits. Aucun parti pris.</description>
  <language>fr</language>
  <lastBuildDate>{now}</lastBuildDate>
  <atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
</channel>
</rss>"""

(ROOT / "feed.xml").write_text(xml, encoding="utf-8")
print(f"feed.xml généré — {len(articles)} articles")
