from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "essai-fournisseur-contract-ci.yml"


def test_ci_couvre_le_modele_avant_import() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    runtime = "scripts/essai_fournisseur.py"
    regression = "scripts/test_essai_modele_avant_import.py"
    contract = "scripts/test_essai_fournisseur_ci_contract.py"

    assert text.count(runtime) >= 3, (
        "la CI doit surveiller, compiler et couvrir le runtime d'essai fournisseur"
    )
    assert text.count(regression) >= 3, (
        "la CI doit surveiller, compiler et exécuter la régression modèle avant import"
    )
    assert text.count(contract) >= 3, (
        "le test de contrat doit lui-même être surveillé, compilé et exécuté"
    )
    assert re.search(r"push:\s*\n\s*branches:\s*\[\"main\"\]", text), (
        "un changement direct sur main doit déclencher la CI d'essai fournisseur"
    )


if __name__ == "__main__":
    test_ci_couvre_le_modele_avant_import()
    print("OK: contrat CI de l'essai fournisseur")
