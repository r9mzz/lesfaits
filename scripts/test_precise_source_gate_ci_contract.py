# -*- coding: utf-8 -*-
"""Non-régression du contrat CI du garde de pertinence des sources."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "precise-source-gate-ci.yml"


def test_workflow_targets_native_gate_and_real_test():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"scripts/pipeline.py"' in text
    assert '"scripts/test_pertinence_bloquant.py"' in text
    assert "python scripts/test_pertinence_bloquant.py" in text
    assert "test_zero_precise_sources_gate.py" not in text


def test_workflow_runs_on_push_to_main_for_runtime_changes():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text, "la CI ne protège pas les modifications directes sur main"
    assert "branches: [main]" in text, "le push main doit déclencher le garde de pertinence"
    push_block = text.split("  push:", 1)[1].split("\n\npermissions:", 1)[0]
    assert '"scripts/pipeline.py"' in push_block
    assert '"scripts/test_pertinence_bloquant.py"' in push_block


if __name__ == "__main__":
    test_workflow_targets_native_gate_and_real_test()
    test_workflow_runs_on_push_to_main_for_runtime_changes()
    print("OK — test_precise_source_gate_ci_contract.py")
