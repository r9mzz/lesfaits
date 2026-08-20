"""Contrat CI du garde de symétrie du fact-checker.

La règle vit dans verification_legacy.py et son test déterministe doit être
exécuté aussi bien en PR que lors d'un push direct sur main. Ce test empêche
qu'une modification critique du juge puisse de nouveau atteindre le runtime
sans contrôle automatique.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "verification-provider-ci.yml"


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in text and "branches: [main]" in text, (
        "la CI fournisseur doit se déclencher sur les pushes directs vers main"
    )
    for path in (
        '"scripts/verification_legacy.py"',
        '"scripts/test_juge_symetrie.py"',
        '"scripts/test_verification_symetrie_ci_contract.py"',
    ):
        assert path in text, f"chemin critique non surveillé par la CI : {path}"

    assert "scripts/test_juge_symetrie.py" in text.split("- name: Compiler", 1)[1], (
        "le test de symétrie doit être compilé par la CI"
    )
    assert "python scripts/test_juge_symetrie.py" in text, (
        "le test de symétrie doit être réellement exécuté par la CI"
    )
    assert "python scripts/test_verification_symetrie_ci_contract.py" in text, (
        "le contrat de couverture doit lui-même être exécuté"
    )

    print("OK — la règle de symétrie est couverte en PR et sur main")


if __name__ == "__main__":
    main()
