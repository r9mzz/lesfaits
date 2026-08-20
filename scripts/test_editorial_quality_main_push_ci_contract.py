from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "editorial-quality.yml"


def test_la_ci_editoriale_surveille_les_pushes_main():
    """Un changement direct de pipeline.py sur main doit être testé automatiquement.

    Deux commits de barème du 19/08 ont modifié le runtime directement sur main.
    La CI n'écoutait que pull_request, donc ces changements pouvaient devenir le
    runtime de production sans exécution automatique de la suite éditoriale.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "  push:\n" in text, "la CI éditoriale n'écoute toujours pas les pushes"
    push_block = text.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
    assert "branches:" in push_block and "main" in push_block, (
        "les pushes main ne déclenchent pas la CI éditoriale"
    )
    assert '"scripts/pipeline.py"' in push_block, (
        "pipeline.py peut encore changer directement sur main sans CI éditoriale"
    )
    assert '"scripts/test_bareme_enjeu_divertissement.py"' in push_block, (
        "la régression du barème peut changer directement sur main sans CI"
    )


if __name__ == "__main__":
    test_la_ci_editoriale_surveille_les_pushes_main()
    print("OK — les pushes main critiques déclenchent la CI éditoriale")
