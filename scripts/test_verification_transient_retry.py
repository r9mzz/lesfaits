# -*- coding: utf-8 -*-
"""Régression : timeout/5xx du fact-check ont une seule relance, sans assouplir le fail-closed."""
from __future__ import annotations

import importlib
import os
import sys

# Une panne transitoire peut produire au maximum deux appels au fournisseur :
# l'appel initial et une unique relance. Les 4xx restent immédiats.


def _reload_verification():
    for name in ("verification", "verification_legacy"):
        sys.modules.pop(name, None)
    os.environ.pop("LLM_BASE_URL", None)
    os.environ.pop("LLM_API_KEY", None)
    os.environ["GROQ_API_KEY"] = "cle-test"
    return importlib.import_module("verification")


def test_504_est_relance_une_fois() -> None:
    verification = _reload_verification()
    appels = []

    def fake(*args, **kwargs):
        appels.append(1)
        if len(appels) == 1:
            raise RuntimeError('Groq 504: {"message":"Service unavailable"}')
        return '{"conforme": true}'

    verification._provider_original_llm_call = fake
    assert verification._llm_call("prompt", max_tokens=1500) == '{"conforme": true}'
    assert len(appels) == 2


def test_timeout_est_relance_une_fois() -> None:
    verification = _reload_verification()
    appels = []

    def fake(*args, **kwargs):
        appels.append(1)
        if len(appels) == 1:
            raise verification.requests.Timeout("read timeout")
        return '{"conforme": true}'

    verification._provider_original_llm_call = fake
    assert verification._llm_call("prompt", max_tokens=1500) == '{"conforme": true}'
    assert len(appels) == 2


def test_504_persistant_reste_fail_closed() -> None:
    verification = _reload_verification()
    appels = []

    def fake(*args, **kwargs):
        appels.append(1)
        raise RuntimeError('Groq 504: {"message":"Service unavailable"}')

    verification._provider_original_llm_call = fake
    try:
        verification._llm_call("prompt", max_tokens=1500)
    except RuntimeError as exc:
        assert "504" in str(exc)
    else:
        raise AssertionError("Un 5xx persistant ne doit jamais être accepté")
    assert len(appels) == 2


def test_400_ne_se_reessaie_pas() -> None:
    verification = _reload_verification()
    appels = []

    def fake(*args, **kwargs):
        appels.append(1)
        raise RuntimeError('Groq 400: {"message":"bad request"}')

    verification._provider_original_llm_call = fake
    try:
        verification._llm_call("prompt", max_tokens=1500)
    except RuntimeError as exc:
        assert "400" in str(exc)
    else:
        raise AssertionError("Une erreur de configuration 400 doit rester immédiate")
    assert len(appels) == 1


if __name__ == "__main__":
    test_504_est_relance_une_fois()
    test_timeout_est_relance_une_fois()
    test_504_persistant_reste_fail_closed()
    test_400_ne_se_reessaie_pas()
    print("OK - retry transitoire fact-check")
