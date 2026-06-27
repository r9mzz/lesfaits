"""
Corrige les apostrophes droites en apostrophes typographiques
dans tous les articles HTML existants.
Usage : python scripts/_fix_typo.py
"""
import re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ARTICLES = Path("articles")

STRAIGHT = "'"  # ' apostrophe droite ASCII
CURLY    = "’"  # ' apostrophe typographique francaise

PATTERN  = r"(?<=[a-zA-ZÀ-ɏ])" + STRAIGHT + r"(?=[a-zA-ZÀ-ɏ])"


def fix_article(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    original = html

    html = re.sub(PATTERN, CURLY, html)
    html = html.replace("...", "…")  # ellipse

    if html != original:
        path.write_text(html, encoding="utf-8")
        return True
    return False


fixed = 0
unchanged = 0

for path in sorted(ARTICLES.glob("*.html")):
    if fix_article(path):
        fixed += 1
        print(f"  OK {path.name}")
    else:
        unchanged += 1

print(f"\nTermine -- {fixed} articles corriges, {unchanged} deja corrects")
