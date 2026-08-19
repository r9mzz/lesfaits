# -*- coding: utf-8 -*-
"""Empêche la régression typographique des citations de redevenir orpheline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "editorial-quality.yml"


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    target = "scripts/test_citations_ponctuation.py"
    contract = "scripts/test_citations_ponctuation_ci_contract.py"
    assert text.count(target) >= 3, (
        "test_citations_ponctuation.py doit être surveillé, compilé et exécuté par Qualité éditoriale"
    )
    assert text.count(contract) >= 3, (
        "le contrat CI de ponctuation doit être surveillé, compilé et exécuté"
    )
    print("OK — régression ponctuation/citations couverte par Qualité éditoriale")


if __name__ == "__main__":
    main()
