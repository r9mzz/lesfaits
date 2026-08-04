# -*- coding: utf-8 -*-
"""Retire un article publié : stub de redirection + sortie de l'index.

Remplace `purge_execute.py`, qui portait une liste de 12 slugs codée en dur
pour une purge ponctuelle de juillet et n'était pas rejouable. Ici le slug est
un argument, la catégorie est lue dans l'index, et le script est idempotent.

    python scripts/retirer_article.py <slug>
    python scripts/retirer_article.py <slug> --dry-run

Ce que ça fait :
  1. remplace `articles/<slug>.html` par un stub (canonical + meta-refresh vers
     la page catégorie) — l'URL ne devient jamais un 404, elle redirige ;
  2. retire l'entrée de `data/articles.json`.

Ce que ça NE fait PAS, volontairement :
  - écrire dans `corrections.html`. Un motif de retrait est un texte éditorial,
    il s'écrit à la main. Un retrait non documenté est une seconde erreur ;
  - déployer. Le prochain `--rebuild` régénère index, catégories, archive,
    feed, sitemap et la page Brèves sans ce slug.
"""
import argparse
import json
import sys
from pathlib import Path

# La console Windows est en cp1252 : sans ça, un simple « ✓ » fait planter le
# script APRÈS l'écriture du stub et AVANT le retrait de l'index, laissant
# l'article à moitié retiré. Constaté le 03/08.
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent

CAT_LABELS = {
    "science": "Science", "economie": "Économie", "tech": "Tech",
    "sante": "Santé", "environnement": "Environnement", "societe": "Société",
}


def stub(cat: str) -> str:
    label = CAT_LABELS.get(cat, cat.capitalize())
    url = f"/categories/{cat}.html"
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<link rel="canonical" href="https://lesfaits.info{url}">
<meta http-equiv="refresh" content="0; url={url}">
<title>Article retiré — Les Faits</title>
<!-- LF_ARTICLE_RETIRE -->
</head>
<body>
<p>Cet article a été retiré. Les retraits sont documentés sur la page
<a href="/corrections.html">Corrections publiques</a>.
Redirection vers la rubrique <a href="{url}">{label}</a>…</p>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    idx_path = ROOT / "data" / "articles.json"
    arts = json.loads(idx_path.read_text(encoding="utf-8"))
    entree = next((a for a in arts if a.get("slug") == args.slug), None)
    path = ROOT / "articles" / f"{args.slug}.html"

    if entree is None and not path.exists():
        print(f"[RIEN À FAIRE] '{args.slug}' n'est ni dans l'index ni dans articles/.")
        return 1

    # Déjà retiré : ne PAS réécrire le stub. La catégorie de redirection vient
    # de l'entrée d'index, qui a disparu au premier passage — une seconde
    # exécution retomberait sur le repli « societe » et casserait silencieusement
    # une redirection correcte. Constaté le 03/08 en testant l'idempotence.
    if path.exists() and "LF_ARTICLE_RETIRE" in path.read_text(encoding="utf-8"):
        print(f"[DÉJÀ RETIRÉ] '{args.slug}' est déjà un stub — redirection laissée intacte.")
        if entree is not None:
            reste = [a for a in arts if a.get("slug") != args.slug]
            idx_path.write_text(json.dumps(reste, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ entrée d'index résiduelle retirée : {len(arts)} → {len(reste)}")
        return 0

    cat = (entree or {}).get("categorie", "societe")
    titre = (entree or {}).get("titre", "(titre inconnu)")
    print(f"  article  : {titre}")
    print(f"  slug     : {args.slug}")
    print(f"  redirige : /categories/{cat}.html")

    if args.dry_run:
        print("\n  (dry-run — rien écrit)")
        return 0

    path.write_text(stub(cat), encoding="utf-8")
    print(f"  ✓ stub écrit : articles/{args.slug}.html")

    if entree is not None:
        reste = [a for a in arts if a.get("slug") != args.slug]
        idx_path.write_text(json.dumps(reste, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✓ data/articles.json : {len(arts)} → {len(reste)} entrées")
    else:
        print("  · absent de l'index, rien à retirer")

    print("\n  Reste à faire : documenter le retrait dans corrections.html,")
    print("  puis `python scripts/pipeline.py --rebuild`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
