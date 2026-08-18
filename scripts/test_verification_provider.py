# -*- coding: utf-8 -*-
"""Régression : le fact-checker doit suivre le fournisseur/modèle du runtime."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _probe(env_overrides: dict[str, str]) -> str:
    env = os.environ.copy()
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "GROQ_MODEL_OVERRIDE", "GROQ_API_KEY"):
        env.pop(key, None)
    env.update(env_overrides)
    code = (
        "import verification; "
        "print(verification.GROQ_MODEL); "
        "print(verification.GROQ_URL); "
        "print('|'.join(verification.GROQ_KEYS))"
    )
    return subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=str(HERE),
        env=env,
        text=True,
    )


def main() -> None:
    provider = _probe({
        "LLM_BASE_URL": "https://api.mistral.ai/v1/",
        "LLM_API_KEY": "provider-test-key",
        "GROQ_MODEL_OVERRIDE": "mistral-small-latest",
        "GROQ_API_KEY": "groq-should-not-be-used",
    }).splitlines()
    assert provider == [
        "mistral-small-latest",
        "https://api.mistral.ai/v1/chat/completions",
        "provider-test-key",
    ], provider

    groq = _probe({"GROQ_API_KEY": "groq-test-key"}).splitlines()
    assert groq == [
        "openai/gpt-oss-120b",
        "https://api.groq.com/openai/v1/chat/completions",
        "groq-test-key",
    ], groq

    print("OK — fact-checker aligné sur fournisseur, modèle et clé du runtime")


if __name__ == "__main__":
    main()
