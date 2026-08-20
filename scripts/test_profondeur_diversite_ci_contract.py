"""Contrat CI : les régressions profondeur/diversité doivent rester exécutées.

Ces deux tests protègent des changements directs du runtime de sélection et de
profondeur de lecture. Les ajouter au dépôt sans les exécuter en CI laisserait
un faux sentiment de couverture.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "profondeur-diversite-contract.yml"


def test_workflow_surveille_et_execute_les_deux_regressions():
    txt = WORKFLOW.read_text(encoding="utf-8")
    for name in ("test_diversite_selection.py", "test_profondeur_lecture.py"):
        # Une occurrence dans paths ne suffit pas : le test doit aussi être
        # réellement lancé. Exiger au moins trois mentions couvre path,
        # compilation et exécution.
        assert txt.count(name) >= 3, f"{name} n'est pas réellement couvert en CI"
        assert f"python scripts/{name}" in txt, f"{name} n'est pas exécuté"


def test_workflow_couvre_le_vrai_runtime_et_son_propre_contrat():
    txt = WORKFLOW.read_text(encoding="utf-8")
    assert '"scripts/pipeline.py"' in txt
    assert "python scripts/test_profondeur_diversite_ci_contract.py" in txt
    assert "pull_request:" in txt
    assert "push:" in txt and "main" in txt


if __name__ == "__main__":
    test_workflow_surveille_et_execute_les_deux_regressions()
    test_workflow_couvre_le_vrai_runtime_et_son_propre_contrat()
    print("OK — contrat CI profondeur/diversité")
