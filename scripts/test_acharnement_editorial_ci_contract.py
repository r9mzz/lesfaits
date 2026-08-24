"""Verrouille la couverture CI du garde anti-acharnement éditorial."""
from pathlib import Path


WORKFLOW = Path(".github/workflows/editorial-quality.yml")
TARGET = "scripts/test_acharnement_editorial.py"
SELF = "scripts/test_acharnement_editorial_ci_contract.py"


def test_workflow_surveille_et_execute_acharnement():
    text = WORKFLOW.read_text(encoding="utf-8")
    # Le test de régression doit déclencher la CI, être compilé et réellement exécuté.
    assert text.count(TARGET) >= 4, "test_acharnement_editorial.py n'est pas couvert partout par la CI"
    assert f"python {TARGET}" in text, "le test anti-acharnement n'est pas exécuté"
    assert text.count(SELF) >= 4, "le contrat CI n'est pas lui-même couvert"
    assert f"python {SELF}" in text, "le contrat CI n'est pas exécuté"


if __name__ == "__main__":
    test_workflow_surveille_et_execute_acharnement()
    print("1 test OK")
