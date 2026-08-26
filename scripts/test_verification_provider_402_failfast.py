# -*- coding: utf-8 -*-
"""Régression : un HTTP 402 du fournisseur de vérification ne doit pas être retenté."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest


class VerificationProvider402FailFastTest(unittest.TestCase):
    def test_second_call_is_blocked_without_new_network_attempt(self):
        calls = {"count": 0}

        legacy = types.ModuleType("verification_legacy")
        legacy.PROMPT_DETECTION = "prompt"
        legacy.GROQ_KEYS = ["mistral-test-key"]
        legacy.GROQ_MODEL = "legacy"
        legacy.GROQ_URL = "https://example.invalid"
        legacy._CLES_MORTES_JOUR = set()

        def failing_llm_call(*args, **kwargs):
            calls["count"] += 1
            raise RuntimeError(
                'Groq 402: {"message":"You must be subscribed to this plan to use the API"}'
            )

        legacy._llm_call = failing_llm_call
        legacy.corriger = lambda art, *args, **kwargs: art
        legacy.detecter = lambda art, *args, **kwargs: {"conforme": True, "problemes": []}
        legacy.verifier_article = lambda art, *args, **kwargs: (art, "erreur_verification")
        legacy._log = lambda *args, **kwargs: None

        keys_module = types.ModuleType("cles_fournisseur")
        keys_module.cles_fournisseur = lambda: ["mistral-test-key"]
        model_module = types.ModuleType("modele_fournisseur")
        model_module.modele_redaction = lambda: "mistral-large-latest"

        saved_modules = {
            name: sys.modules.get(name)
            for name in ("verification_legacy", "cles_fournisseur", "modele_fournisseur")
        }
        old_base = os.environ.get("LLM_BASE_URL")
        os.environ["LLM_BASE_URL"] = "https://api.mistral.ai/v1"
        sys.modules["verification_legacy"] = legacy
        sys.modules["cles_fournisseur"] = keys_module
        sys.modules["modele_fournisseur"] = model_module

        try:
            path = Path(__file__).with_name("verification.py")
            spec = importlib.util.spec_from_file_location("verification_402_under_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)

            with self.assertRaisesRegex(RuntimeError, r"Mistral 402"):
                module._provider_auth_rotating_llm_call("prompt")
            self.assertEqual(calls["count"], 1)

            # Le même processus doit refuser immédiatement : aucun deuxième
            # appel au client HTTP historique n'est autorisé.
            with self.assertRaisesRegex(RuntimeError, r"Mistral 402"):
                module._provider_auth_rotating_llm_call("prompt")
            self.assertEqual(calls["count"], 1)
        finally:
            if old_base is None:
                os.environ.pop("LLM_BASE_URL", None)
            else:
                os.environ["LLM_BASE_URL"] = old_base
            for name, value in saved_modules.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
            sys.modules.pop("verification_402_under_test", None)


if __name__ == "__main__":
    unittest.main()
