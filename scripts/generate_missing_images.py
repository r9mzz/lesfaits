"""
Genere les images manquantes pour tous les articles existants.
Logique : Wikimedia Commons -> Openverse -> fallback Pillow
Usage : python scripts/generate_missing_images.py
"""
import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from scripts.pipeline import (
    _download_hero, _generate_fallback_image, _sanitize_image_keyword, _slug_ascii,
)
from bs4 import BeautifulSoup

ARTICLES_DIR = Path("articles")
IMAGES_DIR   = Path("assets/images")

n_photo    = 0
n_fallback = 0
n_errors   = 0
n_skipped  = 0

articles = sorted(ARTICLES_DIR.glob("*.html"))
print(f"{len(articles)} articles a verifier...\n")

for path in articles:
    slug = path.stem
    safe = _slug_ascii(slug)
    dest = str(IMAGES_DIR / f"{safe}.jpg")

    if os.path.exists(dest) and os.path.getsize(dest) > 5000:
        n_skipped += 1
        continue

    try:
        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("title")
        title = title_tag.get_text().replace(" - Les Faits", "").replace(" — Les Faits", "").strip() if title_tag else slug

        cat_tag = soup.find("meta", attrs={"property": "article:section"})
        category = (cat_tag.get("content") or "societe").lower() if cat_tag else "societe"

        keyword = _sanitize_image_keyword("", fallback=safe) or title[:60]
    except Exception as e:
        print(f"  ERREUR lecture {path.name}: {e}")
        n_errors += 1
        continue

    size_before = os.path.getsize(dest) if os.path.exists(dest) else 0

    try:
        _download_hero(keyword, slug, dest)
    except Exception as e:
        print(f"  ERREUR image {slug}: {e}")
        n_errors += 1
        continue

    if not os.path.exists(dest) or os.path.getsize(dest) < 5000:
        _generate_fallback_image(title, category, slug, dest)
        result = "fallback-direct"
        n_fallback += 1
    else:
        size_after = os.path.getsize(dest)
        if size_after < 200_000 and size_before == 0:
            result = "infographie"
            n_fallback += 1
        else:
            result = "photo"
            n_photo += 1

    print(f"  {result:15s} {slug[:55]}")

print(f"\n{'='*60}")
print(f"Photos       : {n_photo}")
print(f"Infographies : {n_fallback}")
print(f"Erreurs      : {n_errors}")
print(f"Deja OK      : {n_skipped}")
print(f"Total traites: {len(articles) - n_skipped}")
