from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nuances-conditionnelles-ci.yml"


def test_la_ci_couvre_la_regression_des_nuances_conditionnelles():
    """Le test du prompt nuances doit rester exécuté quand le runtime change."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"scripts/pipeline.py"' in text, "pipeline.py ne déclenche pas la CI nuances"
    assert '"scripts/test_nuances_conditionnelles.py"' in text, (
        "le test nuances ne déclenche pas sa propre CI"
    )
    assert "python -m py_compile" in text, "la CI nuances ne vérifie pas la syntaxe"
    assert "scripts/test_nuances_conditionnelles.py" in text.split("python -m py_compile", 1)[1], (
        "le test nuances n'est pas compilé"
    )
    assert "python scripts/test_nuances_conditionnelles.py" in text, (
        "le test nuances n'est pas réellement exécuté"
    )
    assert "python scripts/test_nuances_conditionnelles_ci_contract.py" in text, (
        "le contrat CI nuances n'est pas auto-vérifié"
    )


if __name__ == "__main__":
    test_la_ci_couvre_la_regression_des_nuances_conditionnelles()
    print("OK — la CI couvre réellement les nuances conditionnelles")
