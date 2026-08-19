# -*- coding: utf-8 -*-
"""Régression : une heure canonique doit être persistée sur main, pas seulement réparable en mémoire.

La PR #89 savait corriger l'heure d'Inflation lorsqu'un normaliseur était exécuté,
mais l'état versionné de main restait encore à 13h57 après fusion. Ce contrat
verrouille le mécanisme qui exécute la réparation sur chaque changement du
registre/du workflow et pousse effectivement l'état corrigé sur main.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publication-times.yml"
text = WORKFLOW.read_text(encoding="utf-8")

required = [
    "push:",
    "branches: [main]",
    '"scripts/repair_publication_time_overrides.py"',
    '"scripts/test_publication_override_persistence_contract.py"',
    "persist-overrides:",
    "permissions:",
    "contents: write",
    "python scripts/repair_publication_time_overrides.py",
    "python scripts/repair_publication_time_overrides.py --check",
    'git commit -m "fix: persister les heures publiques canoniques"',
    "git push",
]

missing = [needle for needle in required if needle not in text]
assert not missing, (
    "Le workflow d'horodatage ne persiste pas complètement les overrides canoniques : "
    + ", ".join(missing)
)

print("OK — les heures canoniques sont réparées, contrôlées puis persistées sur main")
