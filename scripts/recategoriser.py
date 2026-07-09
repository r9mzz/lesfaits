#!/usr/bin/env python3
"""
recategoriser.py — one-shot : réapplique detect_category() (lexique v2) aux
articles existants. Met à jour data/search.json + les marqueurs de catégorie
dans chaque article HTML (badge principal, articleSection JSON-LD, breadcrumb).
Les pages index/catégories/archive et les cartes "À lire aussi" sont
régénérées par le rebuild au déploiement — pas touchées ici.
"""
import json, sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
import os
os.environ.setdefault("GROQ_API_KEY", "x")
from pipeline import detect_category  # noqa: E402

ROOT = Path(__file__).parent.parent

LABELS_UP = {"societe": "SOCIÉTÉ", "science": "SCIENCE", "economie": "ÉCONOMIE",
             "tech": "TECH", "sante": "SANTÉ", "environnement": "ENVIRONNEMENT"}
NOMS = {"societe": "Société", "science": "Science", "economie": "Économie",
        "tech": "Tech", "sante": "Santé", "environnement": "Environnement"}

# Corrections manuelles : cas où le lexique se trompe encore (vérifié à la main)
OVERRIDES = {
    # slug (sous-chaîne) : catégorie imposée
    "vie-terre": "science",          # "La vie sur Terre pourrait durer..." = science
    "chapsvision": "tech",           # remplacement de Palantir à la DGSI = tech
}


def patch_article(slug: str, old: str, new: str) -> bool:
    f = ROOT / "articles" / f"{slug}.html"
    if not f.exists():
        print(f"  [SKIP] {slug}.html introuvable")
        return False
    html = f.read_text(encoding="utf-8")
    orig = html
    # 1. Badge principal (première occurrence seulement — les suivantes sont
    #    les cartes "À lire aussi" d'autres articles)
    html = html.replace(f'cat--{old}">{LABELS_UP[old]}', f'cat--{new}">{LABELS_UP[new]}', 1)
    # 2. JSON-LD NewsArticle
    html = html.replace(f'"articleSection":"{old}"', f'"articleSection":"{new}"')
    # 3. Breadcrumb JSON-LD (nom + URL de la catégorie)
    html = html.replace(
        f'"name":"{NOMS[old]}","item":"https://lesfaits.info/categories/{old}.html"',
        f'"name":"{NOMS[new]}","item":"https://lesfaits.info/categories/{new}.html"',
    )
    if html == orig:
        print(f"  [WARN] {slug} : aucun marqueur remplacé")
        return False
    f.write_text(html, encoding="utf-8")
    return True


def main():
    apply = "--apply" in sys.argv
    sf = ROOT / "data" / "search.json"
    data = json.loads(sf.read_text(encoding="utf-8"))
    n = 0
    for a in data:
        old = a["categorie"]
        new = detect_category(a["titre"] + " " + (a.get("excerpt") or ""))
        for frag, forced in OVERRIDES.items():
            if frag in a["slug"]:
                new = forced
        if new == old:
            continue
        n += 1
        print(f"{old:>13} -> {new:<13} {a['slug'][:50]}")
        if apply:
            if patch_article(a["slug"], old, new):
                a["categorie"] = new
    if apply:
        sf.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{n} article(s) recatégorisé(s) — search.json mis à jour")
    else:
        print(f"\n{n} changement(s) — relancer avec --apply pour appliquer")


if __name__ == "__main__":
    main()
