"""Verrouille la couverture CI des régressions sélection/correction ajoutées le 21/08.

Le défaut couvert ici n'est pas éditorial : les tests existaient mais n'étaient
exécutés par aucune CI. Ce contrat empêche qu'ils redeviennent orphelins.
"""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "latest-selection-correction-ci.yml"


def test_workflow_surveille_les_fichiers_critiques():
    txt = WORKFLOW.read_text(encoding="utf-8")
    for path in (
        "scripts/pipeline.py",
        "scripts/verification_legacy.py",
        "scripts/test_selection_sujets_manques.py",
        "scripts/test_correction_motifs_bloquants.py",
        "scripts/test_latest_selection_correction_ci_contract.py",
    ):
        assert path in txt, f"fichier critique absent des déclencheurs/contrôles CI : {path}"


def test_workflow_execute_reellement_les_deux_regressions():
    txt = WORKFLOW.read_text(encoding="utf-8")
    for cmd in (
        "python scripts/test_selection_sujets_manques.py",
        "python scripts/test_correction_motifs_bloquants.py",
        "python scripts/test_latest_selection_correction_ci_contract.py",
    ):
        assert cmd in txt, f"test présent dans le dépôt mais non exécuté par la CI : {cmd}"


def test_workflow_couvre_push_main_et_pull_request():
    txt = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in txt and "branches: [main]" in txt
    assert "pull_request:" in txt


if __name__ == "__main__":
    test_workflow_surveille_les_fichiers_critiques()
    test_workflow_execute_reellement_les_deux_regressions()
    test_workflow_couvre_push_main_et_pull_request()
    print("OK — les régressions sélection/correction sont réellement couvertes en CI")
