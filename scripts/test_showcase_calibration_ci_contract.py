"""Contrat CI du recalibrage de la grille vitrine.

Le test de calibrage doit être déclencheur de la CI éditoriale, compilé et
réellement exécuté. Le présent contrat doit lui-même rester couvert pour éviter
qu'une future édition du workflow ne rende silencieusement cette régression
orpheline.
"""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "editorial-quality.yml"


def test_calibrage_vitrine_est_couvert_par_ci():
    text = WORKFLOW.read_text(encoding="utf-8")
    target = "scripts/test_grille_vitrine_calibrage.py"
    # push + pull_request + py_compile + exécution
    assert text.count(target) >= 4, (
        "test_grille_vitrine_calibrage.py doit déclencher la CI, être compilé "
        "et exécuté"
    )
    assert f"python {target}" in text, "le test de calibrage doit être réellement exécuté"


def test_contrat_est_lui_meme_couvert():
    text = WORKFLOW.read_text(encoding="utf-8")
    target = "scripts/test_showcase_calibration_ci_contract.py"
    assert text.count(target) >= 4, (
        "le contrat de couverture doit déclencher la CI, être compilé et exécuté"
    )
    assert f"python {target}" in text


if __name__ == "__main__":
    test_calibrage_vitrine_est_couvert_par_ci()
    test_contrat_est_lui_meme_couvert()
    print("2 tests OK")
