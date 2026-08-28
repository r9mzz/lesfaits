# -*- coding: utf-8 -*-
"""Régression : une opinion explicitement attribuée ne doit pas être reclassée en fait."""
import os
import sys
import unittest

os.environ.pop("LLM_BASE_URL", None)
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, os.path.dirname(__file__))
import verification


class AccusationAttributionExpliciteTest(unittest.TestCase):
    def test_qualification_attribuee_a_des_patron_est_ecartee(self):
        probleme = {
            "bloc": 1,
            "type": "accusation_presentee_comme_fait",
            "description": (
                "Le résumé présente les qualificatifs « hors-sol » comme un constat neutre, "
                "alors qu'il s'agit d'une opinion attribuée à des patrons."
            ),
            "phrase": (
                "Selon Europe1, plusieurs patrons ont qualifié certaines propositions de "
                "« hors-sol », estimant qu’elles manquaient de réalisme économique."
            ),
        }
        self.assertTrue(verification._accusation_opinion_explicitement_attribuee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [])

    def test_jugement_passif_avec_agent_explicit_est_ecarte(self):
        probleme = {
            "bloc": 1,
            "type": "accusation_presentee_comme_fait",
            "description": (
                "La phrase présente le risque comme un fait établi, alors qu'il s'agit "
                "d'une opinion attribuée à des économistes."
            ),
            "phrase": (
                "L’annulation d’une partie de la dette détenue par la BCE est jugée risquée "
                "par certains économistes, qui estiment qu’elle pourrait affaiblir la crédibilité financière."
            ),
        }
        self.assertTrue(verification._accusation_opinion_explicitement_attribuee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [])

    def test_accusation_non_attribuee_reste_bloquante(self):
        probleme = {
            "bloc": 1,
            "type": "accusation_presentee_comme_fait",
            "description": "L'article présente directement une accusation comme un fait établi.",
            "phrase": "Le dirigeant a détourné des fonds publics pour son bénéfice personnel.",
        }
        self.assertFalse(verification._accusation_opinion_explicitement_attribuee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])

    def test_jugement_sans_agent_explicit_reste_bloquant(self):
        probleme = {
            "bloc": 1,
            "type": "accusation_presentee_comme_fait",
            "description": "Le jugement n'est attribué à personne dans la phrase.",
            "phrase": "Cette proposition est jugée irresponsable et dangereuse.",
        }
        self.assertFalse(verification._accusation_opinion_explicitement_attribuee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])


if __name__ == "__main__":
    unittest.main()
