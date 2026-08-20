from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "reportage-invente-ci.yml"
REPORTAGE_TEST = "scripts/test_reportage_invente.py"
CONTRACT_TEST = "scripts/test_reportage_invente_ci_contract.py"


def test_la_ci_execute_le_garde_reportage_invente():
    """Le garde runtime doit rester relié à sa régression dans une CI dédiée."""
    text = WORKFLOW.read_text(encoding="utf-8")

    push_block = text.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
    pr_block = text.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
    for block in (push_block, pr_block):
        assert '"scripts/pipeline.py"' in block
        assert f'"{REPORTAGE_TEST}"' in block
        assert f'"{CONTRACT_TEST}"' in block
        assert '".github/workflows/reportage-invente-ci.yml"' in block

    syntax_block = text.split("      - name: Vérifier la syntaxe\n", 1)[1].split(
        "      - name: Vérifier le garde reportage inventé\n", 1
    )[0]
    tests_block = text.split("      - name: Vérifier le garde reportage inventé\n", 1)[1]
    assert "scripts/pipeline.py" in syntax_block
    assert REPORTAGE_TEST in syntax_block
    assert CONTRACT_TEST in syntax_block
    assert f"python {REPORTAGE_TEST}" in tests_block
    assert f"python {CONTRACT_TEST}" in tests_block


if __name__ == "__main__":
    test_la_ci_execute_le_garde_reportage_invente()
    print("OK — le garde reportage inventé est couvert par une CI dédiée")
