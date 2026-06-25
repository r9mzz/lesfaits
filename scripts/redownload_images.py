"""Re-download missing hero images using current keywords from articles.json."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import json
from pathlib import Path
import requests

ROOT = Path(__file__).parent.parent
IMAGES_DIR = ROOT / "assets" / "images"

# Copy _download_hero and helpers from pipeline
import unicodedata

def _slug_ascii(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

_BAD_FILENAME = (
    "map", "flag", "logo", "icon", "diagram", "chart", "graph", "coat",
    "blason", "carte", "drapeau", "schema", "plan_", "seal_", "emblem",
    "stamp", "badge", "symbol", "sign_", "portrait_", "headshot",
)

def _is_bad_image(url, w, h):
    fname = url.rsplit("/", 1)[-1].lower()
    if any(bad in fname for bad in _BAD_FILENAME):
        return True
    if w > 0 and h > 0 and (h / w > 1.4 or w / h < 0.5):
        return True
    return False

def download_hero(keyword, slug, dest):
    import urllib.parse
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    hdrs = {"User-Agent": "LesFaits/1.1 (lesfaits.contact@gmail.com)"}

    # 1. Wikimedia Commons
    try:
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search",
            "gsrnamespace": "6", "gsrsearch": keyword, "gsrlimit": "20",
            "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": "1200"
        })
        r = requests.get(f"https://commons.wikimedia.org/w/api.php?{params}", timeout=10, headers=hdrs)
        pages = sorted(
            r.json().get("query", {}).get("pages", {}).values(),
            key=lambda p: -(p.get("imageinfo", [{}])[0].get("width", 0))
        )
        for page in pages:
            ii = page.get("imageinfo", [{}])[0]
            if ii.get("mime", "") not in ("image/jpeg", "image/png", "image/webp"):
                continue
            img_url = ii.get("thumburl") or ii.get("url", "")
            if not img_url:
                continue
            w = ii.get("thumbwidth") or ii.get("width", 0)
            h = ii.get("thumbheight") or ii.get("height", 0)
            if w < 600 or h < 300:
                continue
            if _is_bad_image(img_url, w, h):
                continue
            img_r = requests.get(img_url, timeout=15, headers=hdrs)
            if img_r.status_code == 200 and len(img_r.content) > 20_000:
                open(dest, "wb").write(img_r.content)
                print(f"    ✓ Wikimedia: {img_url.rsplit('/', 1)[-1][:60]}")
                return True
    except Exception as e:
        print(f"    Wikimedia error: {e}")

    # 2. Openverse
    try:
        import urllib.parse
        q = urllib.parse.urlencode({"q": keyword, "page_size": "10", "license_type": "commercial,modification"})
        ov = requests.get(f"https://api.openverse.org/v1/images/?{q}", timeout=10, headers=hdrs)
        for item in ov.json().get("results", []):
            img_url = item.get("url", "")
            if not img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            w = item.get("width", 0) or 0
            h = item.get("height", 0) or 0
            if _is_bad_image(img_url, w, h):
                continue
            r = requests.get(img_url, timeout=15, headers=hdrs)
            if r.status_code == 200 and len(r.content) > 20_000:
                open(dest, "wb").write(r.content)
                print(f"    ✓ Openverse: {img_url.rsplit('/', 1)[-1][:60]}")
                return True
    except Exception as e:
        print(f"    Openverse error: {e}")

    # 3. Picsum fallback
    safe = _slug_ascii(slug)
    try:
        r = requests.get(f"https://picsum.photos/seed/{safe}/1200/500", timeout=15, headers=hdrs)
        if r.status_code == 200:
            open(dest, "wb").write(r.content)
            print(f"    ✓ picsum fallback")
            return True
    except Exception:
        pass

    print(f"    ✗ FAILED")
    return False


with open(ROOT / "data" / "articles.json", encoding="utf-8") as f:
    articles = json.load(f)

missing = [a for a in articles if not (IMAGES_DIR / f"{a['slug']}.jpg").exists()]
print(f"{len(missing)} images manquantes à télécharger\n")

for a in missing:
    slug = a["slug"]
    keyword = a.get("image_keyword", slug)
    dest = str(IMAGES_DIR / f"{slug}.jpg")
    print(f"  [{slug[:45]}] kw: {keyword}")
    download_hero(keyword, slug, dest)

print("\nTerminé.")
