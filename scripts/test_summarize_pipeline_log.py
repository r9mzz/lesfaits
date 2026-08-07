# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from summarize_pipeline_log import render_markdown, summarize_file, summarize_text


class PipelineSummaryTests(unittest.TestCase):
    def test_published_run_counts_attempts_rejections_and_acceptance(self):
        report = summarize_text(
            """→ Génération [ACTU] : Sujet A
     [REJET VITRINE] contexte trop court
→ Génération [ACTU] : Sujet B
     [REJET SOURCES] seulement deux sources indépendantes
→ Génération [ACTU] : Sujet C
     [VITRINE] ✓ article admis : 910 mots, 7 sources
Terminé — 1 article(s) publié(s)
"""
        )
        self.assertEqual(report["status"], "published")
        self.assertEqual(report["attempts"], 3)
        self.assertEqual(report["accepted_showcase"], 1)
        self.assertEqual(report["final_publications"], 1)
        self.assertEqual(report["rejections"], 2)
        self.assertIn("Publication produite", render_markdown(report))

    def test_quota_stop_is_not_misclassified_as_editorial_failure(self):
        report = summarize_text(
            """→ Génération [ACTU] : Sujet A
     [GROQ] clé 1 : quota JOURNALIER épuisé
  [ARRÊT] Quota Groq épuisé sur toutes les clés
Terminé — 0 article(s) publié(s)
"""
        )
        self.assertEqual(report["status"], "empty_quota")
        self.assertTrue(report["quota_stopped_run"])
        self.assertEqual(report["final_publications"], 0)

    def test_technical_error_has_priority(self):
        report = summarize_text(
            """→ Génération [ACTU] : Sujet A
     [ERREUR JSON] Réponse Groq non parseable
Terminé — 0 article(s) publié(s)
"""
        )
        self.assertEqual(report["status"], "technical_failure")
        self.assertTrue(report["errors"])

    def test_missing_log_returns_a_report_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = summarize_file(Path(tmp) / "absent.log")
        self.assertEqual(report["status"], "missing_log")
        self.assertIn("introuvable", report["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
