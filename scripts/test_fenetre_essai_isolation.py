# -*- coding: utf-8 -*-
import os
import unittest
from unittest.mock import patch

from fenetres_modeles import fenetre_essai


class FenetreEssaiIsolationTest(unittest.TestCase):
    def test_fenetre_seule_ne_modifie_pas_la_production(self):
        with patch.dict(os.environ, {"FENETRE_ESSAI": "123456"}, clear=True):
            self.assertIsNone(fenetre_essai())

    def test_workflow_essai_peut_activer_la_fenetre(self):
        with patch.dict(os.environ, {"ESSAI_FOURNISSEUR": "1", "FENETRE_ESSAI": "123456"}, clear=True):
            self.assertEqual(fenetre_essai(), 123456)

    def test_marqueur_non_exact_reste_inactif(self):
        with patch.dict(os.environ, {"ESSAI_FOURNISSEUR": "true", "FENETRE_ESSAI": "123456"}, clear=True):
            self.assertIsNone(fenetre_essai())


if __name__ == "__main__":
    unittest.main()
