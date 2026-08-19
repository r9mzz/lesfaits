# -*- coding: utf-8 -*-
"""Régression : la CI de vérification doit couvrir le parseur JSON partagé.

Le 19/08, le fact-checker a dû adopter le même lecteur JSON robuste que la
rédaction. Ce test empêche qu'un futur changement de ce parseur ou de sa
régression puisse contourner la CI fournisseur.
"""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "verification-provider-ci.yml"
text = WORKFLOW.read_text(encoding="utf-8")

required = [
    '"scripts/json_robuste.py"',
    '"scripts/test_json_sauts_de_ligne.py"',
    '"scripts/test_verification_json_ci_contract.py"',
    "scripts/json_robuste.py",
    "scripts/test_json_sauts_de_ligne.py",
    "scripts/test_verification_json_ci_contract.py",
    "python scripts/test_json_sauts_de_ligne.py",
    "python scripts/test_verification_json_ci_contract.py",
]

missing = [needle for needle in required if needle not in text]
assert not missing, f"CI fournisseur incomplète pour le parseur JSON partagé: {missing}"

print("OK: parseur JSON partagé et sa régression sont couverts par la CI fournisseur")
