from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "editorial-quality.yml"
REPORTAGE_TEST = "scripts/test_reportage_invente.py"
CONTRACT_TEST = "scripts/test_reportage_invente_ci_contract.py"


def test_la_ci_execute_le_garde_reportage_invente():
    """Le garde runtime doit rester relié à sa régression dans la CI éditoriale."""
    text = WORKFLOW.read_text(encoding="utf-8")

    push_block = text.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
    pr_block = text.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
    assert f'"{REPORTAGE_TEST}"' in push_block
    assert f'"{CONTRACT_TEST}"' in push_block
    assert f'"{REPORTAGE_TEST}"' in pr_block
    assert f'"{CONTRACT_TEST}"' in pr_block

    syntax_block = text.split("      - name: Vérifier la syntaxe\n", 1)[1].split(
        "      - name: Tests de non-régression éditoriale\n", 1
    )[0]
    tests_block = text.split("      - name: Tests de non-régression éditoriale\n", 1)[1].split(
        "      - name: Vérifier la lecture du corpus HTML\n", 1
    )[0]
    assert REPORTAGE_TEST in syntax_block
    assert CONTRACT_TEST in syntax_block
    assert f"python {REPORTAGE_TEST}" in tests_block
    assert f"python {CONTRACT_TEST}" in tests_block


if __name__ == "__main__":
    test_la_ci_execute_le_garde_reportage_invente()
    print("OK — le garde reportage inventé est couvert par la CI éditoriale")
