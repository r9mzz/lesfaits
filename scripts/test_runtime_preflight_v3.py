# -*- coding: utf-8 -*-
"""Non-régression : le vrai runner V3 doit revérifier ses propres garde-fous."""
from __future__ import annotations

import inspect

import run_pipeline_v3 as v3


EXPECTED = {
    "test_run_pipeline_v3.py",
    "test_trusted_source_expansion.py",
    "test_verification_scope.py",
    "test_pertinence_bloquant.py",
}


def test_runtime_suite_covers_every_v3_guard() -> None:
    configured = set(v3._RUNTIME_REGRESSION_TESTS)
    assert EXPECTED <= configured, (
        "Le runtime V3 doit rejouer sélection/wrapper, sourcing fiable, portée "
        "de preuve et garde zéro-source-précise avant production"
    )


def test_main_runs_regressions_before_patching_and_generation() -> None:
    source = inspect.getsource(v3)
    main = source.split('if __name__ == "__main__":', 1)[1]
    positions = [
        main.index("_run_runtime_regressions()"),
        main.index("_patch_verification_evidence_scope()"),
        main.index("_patch_conditional_nuances_runtime()"),
        main.index("legacy.main()"),
    ]
    assert positions == sorted(positions), (
        "Les tests runtime doivent partir avant les patches puis avant legacy.main()"
    )


def test_runtime_regressions_fail_closed() -> None:
    source = inspect.getsource(v3._run_runtime_regressions)
    assert "if not test_path.exists()" in source
    assert "raise RuntimeError" in source
    assert "check=True" in source


def main() -> None:
    test_runtime_suite_covers_every_v3_guard()
    test_main_runs_regressions_before_patching_and_generation()
    test_runtime_regressions_fail_closed()
    print("OK — prévol runtime V3 verrouillé")


if __name__ == "__main__":
    main()
