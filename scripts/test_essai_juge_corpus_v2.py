# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

import essai_juge_corpus_v2 as diag


class DiagnosticPopulationTest(unittest.TestCase):
    def test_ne_presente_pas_les_actus_comme_baseline_zero(self) -> None:
        fake_verification = types.SimpleNamespace(
            GROQ_MODEL="mistral-large-latest",
            detecter=lambda art, article_type="actu": {
                "problemes": ([{"type": "chiffre_errone", "gravite": "majeur"}]
                              if art["titre"] == "actu-b" else [])
            },
        )
        article = lambda slug: {
            "titre": slug,
            "resume": ["r"],
            "corps": {"faits": "f", "contexte": "", "nuances": ""},
            "sources": [{"url": "https://example.test", "titre": "s", "institution": ""}],
        }

        out = io.StringIO()
        with (
            patch.object(diag.base, "meilleurs_slugs", return_value=["zero-a"]),
            patch.object(diag.base, "meilleures_actus", return_value=["actu-b"]),
            patch.object(diag.base, "lire_article", side_effect=article),
            patch.object(diag.base, "format_publie", return_value="actu"),
            patch.dict(sys.modules, {"verification": fake_verification}),
            patch.object(sys, "argv", ["essai_juge_corpus_v2.py"]),
            contextlib.redirect_stdout(out),
        ):
            rc = diag.main()

        texte = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("GROUPE A: 0/1 recalé(s)", texte)
        self.assertIn("0 problème détecté à l'époque", texte)
        self.assertIn("GROUPE B: 1/1 recalé(s)", texte)
        self.assertIn("problemes_initiaux non nuls possibles", texte)
        self.assertIn("sévérité du juge se lit d'abord sur le GROUPE A", texte)
        self.assertNotIn("fact-checker de l'époque en avait trouvé ZÉRO", texte)

    def test_aucune_reponse_api_ne_donne_pas_un_faux_vert(self) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("API indisponible")

        fake_verification = types.SimpleNamespace(GROQ_MODEL="m", detecter=boom)
        article = {
            "titre": "zero-a",
            "resume": ["r"],
            "corps": {"faits": "f", "contexte": "", "nuances": ""},
            "sources": [{"url": "https://example.test", "titre": "s", "institution": ""}],
        }
        with (
            patch.object(diag.base, "meilleurs_slugs", return_value=["zero-a"]),
            patch.object(diag.base, "meilleures_actus", return_value=[]),
            patch.object(diag.base, "lire_article", return_value=article),
            patch.object(diag.base, "format_publie", return_value="actu"),
            patch.dict(sys.modules, {"verification": fake_verification}),
            patch.object(sys, "argv", ["essai_juge_corpus_v2.py"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(diag.main(), 1)


if __name__ == "__main__":
    unittest.main()
