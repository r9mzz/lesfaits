# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_pipeline import (  # noqa: E402
    _apply_sensitive_topic_prefilter,
    _apply_showcase_format_policy,
    _article_slugs,
    _generated_article_paths,
)


class RunPipelineSafetyTests(unittest.TestCase):
    def test_only_files_created_during_run_are_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            (articles / "ancien-a.html").write_text("ancienne version", encoding="utf-8")
            (articles / "ancien-b.html").write_text("ancienne version", encoding="utf-8")

            before = _article_slugs(root)

            # Le rebuild modifie des anciens fichiers : ils ne doivent jamais
            # être requalifiés en nouveaux articles.
            (articles / "ancien-a.html").write_text("bloc lié actualisé", encoding="utf-8")
            (articles / "ancien-b.html").write_text("bloc lié actualisé", encoding="utf-8")
            (articles / "nouvel-article.html").write_text("nouveau", encoding="utf-8")

            result = _generated_article_paths(before, root)
            self.assertEqual(result, {(articles / "nouvel-article.html").resolve()})

    def test_retirement_stub_created_before_snapshot_is_not_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            (articles / "article-consolide.html").write_text("stub", encoding="utf-8")

            before = _article_slugs(root)
            (articles / "article-neuf.html").write_text("nouveau", encoding="utf-8")

            result = _generated_article_paths(before, root)
            self.assertNotIn((articles / "article-consolide.html").resolve(), result)
            self.assertIn((articles / "article-neuf.html").resolve(), result)

    def test_deleted_old_article_is_not_reported_as_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            old = articles / "ancien.html"
            old.write_text("ancien", encoding="utf-8")
            before = _article_slugs(root)
            old.unlink()

            self.assertEqual(_generated_article_paths(before, root), set())

    def test_sensitive_legal_topics_are_prefiltered_before_generation(self):
        patched = _apply_sensitive_topic_prefilter("BLACKLIST = [\n    'fait divers',\n]\n")
        for term in ("plainte ", "enquête ouverte", "mise en examen", "agression"):
            self.assertIn(repr(term), patched)
        self.assertNotIn(repr("enquête"), patched)

    def test_sensitive_prefilter_fails_closed_if_pipeline_changes(self):
        with self.assertRaises(RuntimeError):
            _apply_sensitive_topic_prefilter("AUTRE_LISTE = []\n")

    def test_showcase_laisse_la_conversion_en_breve_active(self):
        """Inversion assumée du 10/08 : la vitrine ne coupe PLUS la conversion.

        Elle la coupait parce que la grille refusait les brèves. Depuis que la
        grille les accepte (showcase_quality._valider_breve), la couper revenait
        à jeter les textes de 270-300 mots que le modèle produit réellement —
        quatre jours sans publication à partir du 05/08.
        """
        source = "CONVERSION_BREVE_SI_COURT = True\nQUOTA_ARTICLES_LONGS = 30\n"
        patched = _apply_showcase_format_policy(source)
        self.assertIn("CONVERSION_BREVE_SI_COURT = True", patched)
        self.assertNotIn("CONVERSION_BREVE_SI_COURT = False", patched)

    def test_showcase_long_budget_covers_full_candidate_selection(self):
        source = "CONVERSION_BREVE_SI_COURT = True\nQUOTA_ARTICLES_LONGS = 30\n"
        patched = _apply_showcase_format_policy(source)
        self.assertIn("QUOTA_ARTICLES_LONGS = max(30, nb_max)", patched)
        self.assertNotIn("QUOTA_ARTICLES_LONGS = 30\n", patched)

    def test_showcase_format_patch_fails_closed_if_pipeline_changes(self):
        # Le marqueur de budget reste patché : son absence doit toujours faire
        # échouer le prévol plutôt que produire un pipeline à moitié adapté.
        with self.assertRaises(RuntimeError):
            _apply_showcase_format_policy("CONVERSION_BREVE_SI_COURT = True\n")
        with self.assertRaises(RuntimeError):
            _apply_showcase_format_policy("AUCUN_MARQUEUR = 0\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)