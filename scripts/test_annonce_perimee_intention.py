# -*- coding: utf-8 -*-
"""Régression run 26/08 : une intention annoncée n'est pas une annonce périmée."""
import os
import sys
import unittest

os.environ.pop("LLM_BASE_URL", None)
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, os.path.dirname(__file__))
import verification


class AnnoncePerimeeIntentionTest(unittest.TestCase):
    def test_annonce_passee_d_un_projet_futur_est_ecartee(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "La phrase présente comme un fait accompli ce qui est décrit "
                "dans les sources comme une intention ou un projet : vouloir construire."
            ),
            "phrase": (
                "Le 25 août 2026, SpaceX a annoncé vouloir construire une base "
                "spatiale en Louisiane."
            ),
        }
        self.assertTrue(verification._annonce_intention_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [])

    def test_vraie_annonce_devenue_obsolete_reste_bloquante(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Une source plus récente établit que le lancement a déjà eu lieu ; "
                "la formulation à venir est donc dépassée."
            ),
            "phrase": "SpaceX prévoit de lancer la fusée demain.",
        }
        self.assertFalse(verification._annonce_intention_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])

    def test_intention_annoncee_reste_bloquante_si_le_rapport_etablit_un_etat_plus_recent(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Le projet annoncé a été abandonné selon une source plus récente."
            ),
            "phrase": "L'entreprise a annoncé vouloir construire le site.",
        }
        self.assertFalse(verification._annonce_intention_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])


if __name__ == "__main__":
    unittest.main()
