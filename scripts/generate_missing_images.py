"""
Genere les images manquantes pour tous les articles existants.
Ordre : sources article -> Wikimedia -> Openverse -> Pexels -> Pixabay -> Pillow

Usage :
    python scripts/generate_missing_images.py           # articles sans image
    python scripts/generate_missing_images.py --force   # tous les articles
"""
import sys, os, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from scripts.pipeline import (
    _download_hero, _generate_fallback_image, _sanitize_image_keyword, _slug_ascii,
    PEXELS_KEY, PIXABAY_KEY, GROQ_KEY, GROQ_KEY2,
)
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser()
parser.add_argument("--force", action="store_true",
                    help="Regenerer meme les articles qui ont deja une image")
args = parser.parse_args()

ARTICLES_DIR = Path("articles")
IMAGES_DIR   = Path("assets/images")

stats = {"sources": 0, "wikimedia": 0, "openverse": 0,
         "pexels": 0, "pixabay": 0, "pillow": 0,
         "skipped": 0, "errors": 0}

articles = sorted(ARTICLES_DIR.glob("*.html"))
print(f"{len(articles)} articles trouves")
print(f"Pexels  : {'active' if PEXELS_KEY else 'inactif (PEXELS_API_KEY manquant)'}")
print(f"Pixabay : {'active' if PIXABAY_KEY else 'inactif (PIXABAY_API_KEY manquant)'}")
print(f"Groq    : {'active' if (GROQ_KEY or GROQ_KEY2) else 'inactif (mots-cles fallback)'}")
print(f"Mode    : {'--force (regeneration)' if args.force else 'manquants uniquement'}\n")

for path in articles:
    slug = path.stem
    safe = _slug_ascii(slug)
    dest = str(IMAGES_DIR / f"{safe}.jpg")

    if not args.force and os.path.exists(dest) and os.path.getsize(dest) > 5000:
        stats["skipped"] += 1
        continue

    try:
        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("title")
        title = title_tag.get_text().replace(" - Les Faits", "").replace("— Les Faits", "").strip() if title_tag else slug

        cat_tag = soup.find("meta", attrs={"property": "article:section"})
        category = (cat_tag.get("content") or "societe").lower() if cat_tag else "societe"

        desc_tag = soup.find("meta", attrs={"name": "description"})
        summary = desc_tag.get("content", "") if desc_tag else ""

        # Sources depuis le HTML (balises <cite> dans la section sources)
        sources = []
        for li in soup.select("section.sources ol li"):
            a = li.find("a")
            if a and a.get("href"):
                sources.append({"url": a["href"]})

        keyword = _sanitize_image_keyword("", fallback=safe) or title[:60]

        # Supprimer l'ancien fichier en mode --force
        if args.force and os.path.exists(dest):
            os.remove(dest)

    except Exception as e:
        print(f"  ERREUR lecture {path.name}: {e}")
        stats["errors"] += 1
        continue

    try:
        src_type, credit = _download_hero(
            keyword, slug, dest,
            sources=sources,
            title=title,
            summary=summary,
            category=category,
        )
        if src_type in stats:
            stats[src_type] += 1
        else:
            stats["sources"] += 1
    except Exception as e:
        print(f"  ERREUR image {slug}: {e}")
        stats["errors"] += 1

print(f"\n{'='*60}")
print(f"Sources article : {stats['sources']}")
print(f"Wikimedia       : {stats['wikimedia']}")
print(f"Openverse       : {stats['openverse']}")
print(f"Pexels          : {stats['pexels']}")
print(f"Pixabay         : {stats['pixabay']}")
print(f"Infographies    : {stats['pillow']}")
print(f"Erreurs         : {stats['errors']}")
print(f"Deja OK (skip)  : {stats['skipped']}")
total = sum(v for k, v in stats.items() if k not in ("skipped", "errors"))
print(f"Total traites   : {total}")
