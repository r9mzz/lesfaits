# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_pipeline import _article_slugs, _generated_article_paths  # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
