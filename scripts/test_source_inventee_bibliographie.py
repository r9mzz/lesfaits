# -*- coding: utf-8 -*-
"""Régression : une source autorisée mais inutilisée n'est pas une source inventée."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GROQ_API_KEY", "test-key")

import verification  # noqa: E402


class SourceInventeeBibliographieTest(unittest.TestCase):
    def setUp(self):
        self.article = {
            "sources": [
                {
                    "institution": "Egaliteetreconciliation",
                    "titre": "La canicule asymptomatique",
                    "url": "https://example.test/source-autorisee",
                },
                {
                    "institution": "France Info",
                    "titre": "Une autre source",
                    "url": "https://example.test/france-info",
                },
            ]
        }

    def test_entree_bibliographique_autorisee_est_ecartee(self):
        probleme = {
            "bloc": 2,
            "type": "source_inventee",
            "description": "La source est listée dans les sources mais n'est jamais citée dans le texte.",
            "phrase": "Egaliteetreconciliation | La canicule asymptomatique | https://example.test/source-autorisee",
        }
        self.assertTrue(
            verification._provider_source_inventee_bibliographie_autorisee(probleme, self.article)
        )

    def test_url_absente_des_sources_reste_bloquante(self):
        probleme = {
            "bloc": 2,
            "type": "source_inventee",
            "description": "La source n'appartient pas à la liste autorisée.",
            "phrase": "Média inconnu | Article | https://example.test/inventee",
        }
        self.assertFalse(
            verification._provider_source_inventee_bibliographie_autorisee(probleme, self.article)
        )

    def test_mauvaise_attribution_dans_le_texte_reste_bloquante(self):
        probleme = {
            "bloc": 2,
            "type": "source_inventee",
            "description": "Le renvoi [2] ne confirme pas le fait affirmé.",
            "phrase": "La température a atteint 60 °C [2].",
        }
        self.assertFalse(
            verification._provider_source_inventee_bibliographie_autorisee(probleme, self.article)
        )


if __name__ == "__main__":
    unittest.main()
