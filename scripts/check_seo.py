# -*- coding: utf-8 -*-
"""
Test de non-régression SEO — exécuté par deploy.yml après le rebuild.
Échoue (exit 1) si une page requise n'a pas ses balises meta essentielles,
ce qui bloque le déploiement au lieu de publier une page dégradée.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Balises requises par page (regex insensibles à l'ordre des attributs)
REQUIRED = {
    "canonical":    r'<link[^>]+rel="canonical"',
    "og:title":     r'<meta[^>]+property="og:title"',
    "og:image":     r'<meta[^>]+property="og:image"',
    "twitter:card": r'<meta[^>]+name="twitter:card"',
    "description":  r'<meta[^>]+name="description"',
    "lang=fr":      r'<html[^>]+lang="fr"',
}

# Pages statiques à vérifier + le premier article trouvé (représentatif du template)
PAGES = ["index.html", "methode.html", "contact.html", "corrections.html", "archive.html"]


def check(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8", errors="replace")
    return [name for name, rx in REQUIRED.items() if not re.search(rx, html)]


def main() -> int:
    targets = [ROOT / p for p in PAGES if (ROOT / p).exists()]
    articles = sorted((ROOT / "articles").glob("*.html"))
    if articles:
        targets.append(articles[0])
        targets.append(articles[-1])

    failures = 0
    for path in targets:
        missing = check(path)
        # L'archive et certaines pages listes n'exigent pas og:image spécifique,
        # mais toutes doivent avoir canonical + description + lang.
        if missing:
            print(f"[SEO FAIL] {path.relative_to(ROOT)} — manquant : {', '.join(missing)}")
            failures += 1
        else:
            print(f"[SEO OK]   {path.relative_to(ROOT)}")

    # Bonus : le mot littéral "None" dans un bloc sources = bug d'affichage
    none_hits = []
    for art in articles:
        txt = art.read_text(encoding="utf-8", errors="replace")
        if re.search(r"·\s*None\s*[·<]", txt):
            none_hits.append(art.name)
    if none_hits:
        print(f"[SEO FAIL] Champ date 'None' affiché dans : {', '.join(none_hits[:5])}"
              + (f" (+{len(none_hits)-5} autres)" if len(none_hits) > 5 else ""))
        failures += 1

    if failures:
        print(f"\n{failures} page(s) en échec — déploiement bloqué.")
        return 1
    print(f"\nToutes les vérifications SEO passent ({len(targets)} pages).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
