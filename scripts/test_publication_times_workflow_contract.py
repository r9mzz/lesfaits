# -*- coding: utf-8 -*-
"""Contrat CI du workflow d'horodatage public.

Un déploiement sans création d'article ne doit pas lancer la passe
d'horodatage : elle ne ferait que rafraîchir des métadonnées techniques comme
``feed.xml:lastBuildDate`` et créerait un faux changement de publication.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "publication-times.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    required = [
        "Détecter les nouveaux articles du déploiement",
        "git -C /tmp/site diff --name-only --diff-filter=A HEAD~1 HEAD -- 'articles/*.html'",
        'echo "count=$NB_NEW" >> "$GITHUB_OUTPUT"',
        "if: steps.nouveaux.outputs.count != '0'",
        "scripts/test_publication_times_workflow_contract.py",
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise AssertionError(
            "workflow d'horodatage sans garde 0 nouvel article : " + ", ".join(missing)
        )

    if text.count("if: steps.nouveaux.outputs.count != '0'") < 2:
        raise AssertionError(
            "la génération ET la publication des horodatages doivent être bloquées sans nouvel article"
        )

    print("OK: aucun horodatage public n'est lancé quand le déploiement n'ajoute aucun article")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
