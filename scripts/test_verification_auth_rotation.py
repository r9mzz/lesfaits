# -*- coding: utf-8 -*-
"""Régression : une clé 401 ne doit pas condamner les suivantes au fact-check."""
from __future__ import annotations

import importlib
import os
import sys


class _Response:
    def __init__(self, status_code: int, text: str, payload: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def _reload_verification():
    for name in ("verification", "verification_legacy"):
        sys.modules.pop(name, None)
    return importlib.import_module("verification")


def test_401_passe_a_la_cle_suivante() -> None:
    os.environ.pop("LLM_BASE_URL", None)
    os.environ.pop("LLM_API_KEY", None)
    os.environ["GROQ_API_KEY"] = "cle-revoquee"
    os.environ["GROQ_API_KEY_2"] = "cle-valide"

    verification = _reload_verification()
    verification.GROQ_KEYS = ["cle-revoquee", "cle-valide"]
    verification._CLES_MORTES_JOUR.clear()

    appels: list[str] = []

    def fake_post(url, headers, json, timeout):
        token = headers["Authorization"].removeprefix("Bearer ")
        appels.append(token)
        if token == "cle-revoquee":
            return _Response(401, '{"detail":"Invalid API Key"}')
        return _Response(
            200,
            "ok",
            {
                "choices": [{"message": {"content": '{"conforme": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    verification.requests.post = fake_post
    brut = verification._llm_call("prompt court", max_tokens=1500)

    assert brut == '{"conforme": true}'
    assert appels == ["cle-revoquee", "cle-valide"]
    assert verification.GROQ_KEYS == ["cle-valide"]


def test_401_unique_reste_fail_closed() -> None:
    os.environ.pop("LLM_BASE_URL", None)
    os.environ.pop("LLM_API_KEY", None)
    os.environ["GROQ_API_KEY"] = "seule-cle-revoquee"
    os.environ.pop("GROQ_API_KEY_2", None)

    verification = _reload_verification()
    verification.GROQ_KEYS = ["seule-cle-revoquee"]
    verification._CLES_MORTES_JOUR.clear()
    verification.requests.post = lambda *args, **kwargs: _Response(
        401, '{"detail":"Invalid API Key"}'
    )

    try:
        verification._llm_call("prompt court", max_tokens=1500)
    except RuntimeError as exc:
        assert "Aucune clé de vérification valide" in str(exc)
    else:
        raise AssertionError("Une clé unique invalide ne doit jamais être acceptée")


if __name__ == "__main__":
    test_401_passe_a_la_cle_suivante()
    test_401_unique_reste_fail_closed()
    print("OK - rotation auth fact-checker")
