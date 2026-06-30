"""
Détecte et corrige TOUS les articles avec images dupliquées ou trop petites.
Appelé par rebuild.yml — utilise Pexels avec un mot-clé plus spécifique que l'original.
"""
import hashlib, json, os, requests, time

KEY = os.getenv("PEXELS_API_KEY", "")
IMG_DIR = "assets/images"

with open("data/articles.json", encoding="utf-8") as f:
    arts = {a["slug"]: a for a in json.load(f)}

# ── 1. Grouper les images par hash MD5 ───────────────────────────────────────
hash_to_slugs: dict[str, list[str]] = {}
slug_to_hash: dict[str, str] = {}

for fn in os.listdir(IMG_DIR):
    if not fn.endswith(".jpg"):
        continue
    slug = fn[:-4]
    path = os.path.join(IMG_DIR, fn)
    h = hashlib.md5(open(path, "rb").read()).hexdigest()
    hash_to_slugs.setdefault(h, []).append(slug)
    slug_to_hash[slug] = h

# ── 2. Identifier les cibles ─────────────────────────────────────────────────
targets: set[str] = set()

# Doublons : garder le premier (le plus ancien), régénérer les autres
for h, slugs in hash_to_slugs.items():
    if len(slugs) > 1:
        slugs_sorted = sorted(slugs)  # ordre alphabétique → stable
        print(f"  [DOUBLON] hash={h[:8]} → {slugs_sorted}")
        for slug in slugs_sorted[1:]:   # conserver slugs_sorted[0], régénérer le reste
            targets.add(slug)

# Images trop petites (placeholder ou erreur de téléchargement)
for fn in os.listdir(IMG_DIR):
    if fn.endswith(".jpg") and os.path.getsize(os.path.join(IMG_DIR, fn)) < 110_000:
        targets.add(fn[:-4])

print(f"\n{len(targets)} image(s) à régénérer\n")

# Hashes déjà utilisés (pour ne pas reproduire un doublon en régénérant)
used_hashes = {
    h for h, slugs in hash_to_slugs.items()
    if any(s not in targets for s in slugs)  # au moins un article qui garde cette image
}

# ── 3. Régénérer via Pexels ──────────────────────────────────────────────────
used_pexels_ids: set[int] = set()

def pexels_search(query: str, exclude_hashes: set[str]) -> bytes | None:
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "landscape", "per_page": 10, "size": "large"},
            headers={"Authorization": KEY},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        for photo in r.json().get("photos", []):
            pid = photo.get("id", 0)
            if pid in used_pexels_ids:
                continue
            url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large", "")
            if not url:
                continue
            ir = requests.get(url, timeout=12)
            if ir.status_code == 200 and len(ir.content) > 30_000:
                h = hashlib.md5(ir.content).hexdigest()
                if h in exclude_hashes:
                    continue   # même image que quelqu'un d'autre → essayer suivant
                used_pexels_ids.add(pid)
                return ir.content
    except Exception as e:
        print(f"    ERR pexels: {e}")
    return None


def make_query(slug: str, art: dict) -> str:
    """Construit un mot-clé plus précis en combinant titre + catégorie."""
    titre = art.get("titre", slug.replace("-", " "))
    cat = art.get("categorie", "")
    kw = art.get("image_keyword", "")
    # Prendre les 4 premiers mots du titre + catégorie comme contexte
    words = [w for w in titre.replace(":", "").replace("«", "").replace("»", "").split() if len(w) > 3][:4]
    base = " ".join(words)
    if cat and cat not in base.lower():
        base = f"{cat} {base}"
    return base


for slug in sorted(targets):
    art = arts.get(slug, {})
    query = make_query(slug, art)
    print(f"  {slug[:55]:<55} kw='{query[:40]}'", end=" ", flush=True)

    data = pexels_search(query, used_hashes)

    if data is None:
        # Fallback : mot-clé encore plus générique (juste titre)
        fallback = art.get("titre", slug.replace("-", " "))
        data = pexels_search(fallback, used_hashes)

    if data:
        path = os.path.join(IMG_DIR, f"{slug}.jpg")
        open(path, "wb").write(data)
        new_h = hashlib.md5(data).hexdigest()
        used_hashes.add(new_h)
        slug_to_hash[slug] = new_h
        print(f"OK {len(data)//1024}KB")
    else:
        print("SKIP (aucune image unique trouvée)")

    time.sleep(0.4)

print("\nTerminé.")
