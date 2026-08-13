# -*- coding: utf-8 -*-
"""Répare le NameError du juge de pertinence puis délègue au runner V3."""
from __future__ import annotations

import sys

import run_pipeline_v3 as v3

_original = v3._prepared_pipeline_source_v3


def _prepared_pipeline_source_v4() -> str:
    source = _original()
    broken = '_pertinence = juger_pertinence_sources(sujet.get("title", ""), extra)'
    fixed = '_pertinence = juger_pertinence_sources(item.get("title", ""), extra)'
    if source.count(broken) != 1:
        raise RuntimeError("Marqueur pertinence introuvable ou dupliqué")
    source = source.replace(broken, fixed, 1)
    compile(source, str(v3.legacy.PIPELINE), "exec")
    print("[PRÉVOL V4] variable de pertinence documentaire réparée")
    return source


v3.legacy._prepared_pipeline_source = _prepared_pipeline_source_v4

if __name__ == "__main__":
    sys.exit(v3.legacy.main())
