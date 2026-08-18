# -*- coding: utf-8 -*-
"""Contrat CI du workflow d'horodatage public.

Une passe d'horodatage est inutile si aucun article n'a changé, mais elle reste
obligatoire lorsqu'un article existant est reconstruit : le rebuild peut sinon
réintroduire son heure de génération et écraser son heure publique historique.
Le runtime doit passer par ``run_publication_times.py`` afin de restaurer aussi
les articles déjà privés de ``date_iso`` mais dont l'ancien HTML conserve
encore un ``datePublished`` public exploitable.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "publication-times.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    required = [
        "Détecter les articles touchés par le déploiement",
        "git -C /tmp/site diff --name-only --diff-filter=AM HEAD~1 HEAD -- 'articles/*.html'",
        'echo "count=$NB_ARTICLES" >> "$GITHUB_OUTPUT"',
        "if: steps.articles.outputs.count != '0'",
        "scripts/run_publication_times.py",
        "scripts/test_publication_time_legacy_rebuild.py",
        "scripts/test_publication_times_workflow_contract.py",
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise AssertionError(
            "workflow d'horodatage incomplet pour les articles ajoutés/reconstruits : "
            + ", ".join(missing)
        )

    if "--diff-filter=A HEAD~1 HEAD -- 'articles/*.html'" in text:
        raise AssertionError(
            "le garde ne doit pas regarder seulement les créations : un article reconstruit peut perdre son heure publique"
        )

    if "python scripts/stamp_publication_times.py \\" in text:
        raise AssertionError(
            "le runtime ne doit plus appeler directement le script historique : il contournerait la récupération des date_iso perdus"
        )

    if text.count("if: steps.articles.outputs.count != '0'") < 2:
        raise AssertionError(
            "la génération ET la publication des horodatages doivent être bloquées seulement si aucun article n'a changé"
        )

    print("OK: les articles ajoutés ou reconstruits déclenchent la réparation robuste d'horodatage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
