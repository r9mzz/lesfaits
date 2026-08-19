# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import types
import unittest
from unittest.mock import patch

from reserve_verification_quota import reserved_verification_quota


class ReservedVerificationQuotaTests(unittest.TestCase):
    def test_reserves_last_two_distinct_keys_and_restores_environment(self):
        env = {
            "GROQ_API_KEY": "writer-1",
            "GROQ_API_KEY_2": "writer-2",
            "GROQ_API_KEY_3": "writer-3",
            "GROQ_API_KEY_4": "check-1",
            "GROQ_API_KEY_5": "check-2",
        }
        fake = types.SimpleNamespace(GROQ_KEYS=[])
        with patch.dict(os.environ, env, clear=True):
            with reserved_verification_quota(2, fake) as state:
                self.assertTrue(state["enabled"])
                self.assertEqual(state["writer_keys"], 3)
                self.assertEqual(state["reserved"], 2)
                self.assertNotIn("GROQ_API_KEY_4", os.environ)
                self.assertNotIn("GROQ_API_KEY_5", os.environ)
                self.assertEqual(
                    fake.GROQ_KEYS,
                    ["check-1", "check-2", "writer-1", "writer-2", "writer-3"],
                )
            self.assertEqual(os.environ["GROQ_API_KEY_4"], "check-1")
            self.assertEqual(os.environ["GROQ_API_KEY_5"], "check-2")

    def test_does_not_reserve_when_writer_would_have_fewer_than_three_keys(self):
        env = {
            "GROQ_API_KEY": "one",
            "GROQ_API_KEY_2": "two",
            "GROQ_API_KEY_3": "three",
            "GROQ_API_KEY_4": "four",
        }
        fake = types.SimpleNamespace(GROQ_KEYS=[])
        with patch.dict(os.environ, env, clear=True):
            with reserved_verification_quota(2, fake) as state:
                self.assertFalse(state["enabled"])
                self.assertEqual(state["writer_keys"], 4)
                self.assertIn("GROQ_API_KEY_4", os.environ)

    def test_duplicate_key_values_are_not_counted_twice(self):
        env = {
            "GROQ_API_KEY": "same",
            "GROQ_API_KEY_2": "same",
            "GROQ_API_KEY_3": "two",
            "GROQ_API_KEY_4": "three",
            "GROQ_API_KEY_5": "four",
            "GROQ_API_KEY_6": "five",
        }
        fake = types.SimpleNamespace(GROQ_KEYS=[])
        with patch.dict(os.environ, env, clear=True):
            with reserved_verification_quota(2, fake) as state:
                self.assertTrue(state["enabled"])
                self.assertEqual(state["writer_keys"], 3)
                self.assertEqual(fake.GROQ_KEYS[:2], ["four", "five"])

    def test_invalid_setting_fails_before_generation(self):
        fake = types.SimpleNamespace(GROQ_KEYS=[])
        with self.assertRaises(ValueError):
            with reserved_verification_quota(6, fake):
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ProviderUniqueTest(unittest.TestCase):
    """La réservation ne doit JAMAIS écraser la clé du fournisseur unique.

    Panne du 19/08 : `verification.GROQ_KEYS` recevait les clés Groq, qui
    partaient vers l'URL Mistral — 401 sur chaque vérification, 32 articles
    écrits, zéro publié. La réservation protège un quota journalier PAR COMPTE
    Groq ; sur un fournisseur à clé unique, elle n'a rien à répartir.
    """

    def test_llm_api_key_desactive_la_reservation(self):
        fake = types.SimpleNamespace(GROQ_KEYS=["cle-fournisseur"])
        env = {f"GROQ_API_KEY_{i}": f"groq{i}" for i in range(2, 9)}
        env["GROQ_API_KEY"] = "groq1"
        env["LLM_API_KEY"] = "cle-fournisseur"
        with patch.dict(os.environ, env, clear=False):
            with reserved_verification_quota(2, verification_module=fake) as info:
                self.assertFalse(info["enabled"])
                self.assertEqual(fake.GROQ_KEYS, ["cle-fournisseur"])
                # Les clés Groq ne doivent pas non plus être retirées de
                # l'environnement : rien n'est à masquer au rédacteur.
                self.assertEqual(os.getenv("GROQ_API_KEY"), "groq1")


if __name__ == "__main__":
    unittest.main()
