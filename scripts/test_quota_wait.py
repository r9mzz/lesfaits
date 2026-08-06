# -*- coding: utf-8 -*-
"""Non-régression du prévol quota du pipeline de génération."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_pipeline


def main() -> int:
    original = run_pipeline.GROQ_WAIT_MAX_MINUTES
    try:
        run_pipeline.GROQ_WAIT_MAX_MINUTES = 150
        source = run_pipeline._prepared_pipeline_source()
        assert "ATTENTE_MAX_LIBERATION = 150 * 60" in source
        assert "ATTENTE_MAX_LIBERATION = 15 * 60" not in source
        compile(source, str(run_pipeline.PIPELINE), "exec")

        run_pipeline.GROQ_WAIT_MAX_MINUTES = 181
        try:
            run_pipeline._prepared_pipeline_source()
        except ValueError:
            pass
        else:
            raise AssertionError("un délai supérieur au budget doit être refusé")
    finally:
        run_pipeline.GROQ_WAIT_MAX_MINUTES = original

    print("Prévol quota : OK (150 min, borne haute protégée)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
