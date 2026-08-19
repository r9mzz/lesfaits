"""Contrat CI : la régression JSON de génération doit toujours être exécutée."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "editorial-quality.yml"
TEST = "scripts/test_json_generation_guillemets.py"
SELF = "scripts/test_json_generation_ci_contract.py"


def test_le_test_json_generation_est_declenche_compile_et_execute():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    # Le fichier doit apparaître dans : paths, py_compile et exécution.
    assert workflow.count(TEST) >= 3, (
        f"{TEST} n'est pas couvert de bout en bout par Qualité éditoriale "
        f"({workflow.count(TEST)} occurrence(s), 3 attendues au minimum)"
    )
    assert f"python {TEST}" in workflow, (
        "la régression du guillemet JSON n'est pas réellement exécutée"
    )

    # Le contrat lui-même doit rester surveillé et exécuté, sinon il peut devenir
    # orphelin exactement comme le test qu'il protège.
    assert workflow.count(SELF) >= 3, (
        f"{SELF} n'est pas lui-même couvert par la CI"
    )
    assert f"python {SELF}" in workflow


if __name__ == "__main__":
    test_le_test_json_generation_est_declenche_compile_et_execute()
    print("OK — régression JSON de génération couverte par la CI éditoriale")
