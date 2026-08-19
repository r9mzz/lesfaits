# -*- coding: utf-8 -*-
"""Régression : le barème de sélection de pipeline.py doit être réellement testé en CI.

Le 19/08, un correctif a ajouté un signal d'enjeu public pour la cyber/données
personnelles, un malus divertissement pour gaming/cinéma, et corrigé le faux
positif « épisode » sur des épisodes épidémiques. Le test fonctionnel existait,
mais aucune CI ne l'exécutait. Ce contrat empêche ce test de redevenir orphelin.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "editorial-quality.yml"
text = WORKFLOW.read_text(encoding="utf-8")

required = [
    '"scripts/test_bareme_enjeu_divertissement.py"',
    '"scripts/test_bareme_selection_ci_contract.py"',
    "scripts/test_bareme_enjeu_divertissement.py",
    "scripts/test_bareme_selection_ci_contract.py",
    "python scripts/test_bareme_enjeu_divertissement.py",
    "python scripts/test_bareme_selection_ci_contract.py",
]

missing = [needle for needle in required if needle not in text]
assert not missing, (
    "La CI Qualité éditoriale ne couvre pas entièrement le barème de sélection : "
    + ", ".join(missing)
)

print("OK — barème enjeu public/divertissement couvert par la CI éditoriale")
