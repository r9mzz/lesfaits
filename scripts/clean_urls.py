"""Supprime les URLs brutes du corps des articles (hors section sources)."""
import re, sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent

# Regex pour (https://...) ou (http://...) avec contenu éventuel avant la paren fermante
URL_PAREN = re.compile(r'\s*\(https?://[^\)]{5,300}\)', re.IGNORECASE)

count = 0
for p in sorted((ROOT / "articles").glob("*.html")):
    text = p.read_text(encoding="utf-8")

    # Sépare le corps (avant .sources) de la section sources (on ne touche pas aux sources)
    split_marker = '<div class="sources">'
    if split_marker not in text:
        continue

    body_part, sources_part = text.split(split_marker, 1)

    # Nettoie uniquement le corps
    body_clean = URL_PAREN.sub('', body_part)

    if body_clean == body_part:
        continue  # rien à changer

    p.write_text(body_clean + split_marker + sources_part, encoding="utf-8")
    count += 1
    print(f"  OK {p.name}")

print(f"\nTotal: {count} articles nettoyés")
