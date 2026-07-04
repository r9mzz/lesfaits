"""Exécute la purge des 12 articles validés : remplace chaque fichier article
par un stub (meta-refresh + canonical vers la page catégorie) et retire l'entrée
de data/articles.json. Le pipeline de déploiement copiera les stubs vers le site
public ; l'index/sitemap/catégories seront régénérés sans ces 12 slugs."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent

CAT_LABELS = {
    "science": "Science", "economie": "Économie", "tech": "Tech",
    "sante": "Santé", "environnement": "Environnement", "societe": "Société",
}

# slug -> catégorie (page de redirection)
PURGE = {
    "nouvelles-addictions-sante": "science",
    "chantal-delsol-droite-antimoderne": "societe",
    "parapluie-energetique-innovant": "environnement",
    "climatiseurs-portables-fortes-chaleurs": "environnement",
    "sauvetage-poisson-rare-monde": "societe",
    "redevance-pfas-industries-polluantes": "environnement",
    "t-rex-exceptionnel-presentation-new-york": "environnement",
    "washington-reautorise-ia-anthropic": "tech",
    "chine-aimant-fusion-nucleaire": "science",
    "eutrophisation-baie-guanabara-rio": "environnement",
    "coree-du-sud-investit-dans-ia": "tech",
    "hantavirus-terre-de-feu-argentine": "environnement",
}


def stub(cat):
    label = CAT_LABELS.get(cat, cat.capitalize())
    url = f"/categories/{cat}.html"
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="canonical" href="https://lesfaits.info{url}">
<meta http-equiv="refresh" content="0; url={url}">
<title>Article retiré — Les Faits</title>
</head>
<body>
<p>Cet article a été retiré. Redirection vers la rubrique <a href="{url}">{label}</a>…</p>
</body>
</html>
"""


def main():
    # 1. Écrire les stubs
    for slug, cat in PURGE.items():
        path = ROOT / "articles" / f"{slug}.html"
        existait = path.exists()
        path.write_text(stub(cat), encoding="utf-8")
        print(f"  stub écrit ({'remplacé' if existait else 'nouveau'}) : {slug} -> /categories/{cat}.html")

    # 2. Retirer de data/articles.json
    idx_path = ROOT / "data" / "articles.json"
    arts = json.loads(idx_path.read_text(encoding="utf-8"))
    avant = len(arts)
    arts = [a for a in arts if a.get("slug") not in PURGE]
    idx_path.write_text(json.dumps(arts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  data/articles.json : {avant} -> {len(arts)} entrées ({avant - len(arts)} retirées)")


if __name__ == "__main__":
    main()
