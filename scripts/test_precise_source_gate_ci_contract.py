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


if __name__ == "__main__":
    test_workflow_targets_native_gate_and_real_test()
    print("OK — test_precise_source_gate_ci_contract.py")
