# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_retirements import apply_retirements  # noqa: E402


class RetirementTests(unittest.TestCase):
    def test_consolidation_filters_indexes_and_writes_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "articles").mkdir()
            articles = [
                {"slug": "old", "titre": "Ancienne version"},
                {"slug": "best", "titre": "Version complète"},
                {"slug": "other", "titre": "Autre sujet"},
            ]
            (root / "data" / "articles.json").write_text(
                json.dumps(articles, ensure_ascii=False), encoding="utf-8"
            )
            (root / "data" / "search.json").write_text(
                json.dumps(articles, ensure_ascii=False), encoding="utf-8"
            )
            (root / "data" / "pending_x_posts.txt").write_text("old\nother\n", encoding="utf-8")
            (root / "data" / "retirements.json").write_text(json.dumps([{
                "slug": "old", "redirect_to": "best", "date": "2026-08-06",
                "reason": "Doublon consolidé.",
            }]), encoding="utf-8")
            (root / "articles" / "old.html").write_text("ancien", encoding="utf-8")
            (root / "articles" / "best.html").write_text("cible", encoding="utf-8")

            result = apply_retirements(root)
            self.assertTrue(result["changed"])
            kept = json.loads((root / "data" / "articles.json").read_text(encoding="utf-8"))
            self.assertEqual(["best", "other"], [a["slug"] for a in kept])
            search = json.loads((root / "data" / "search.json").read_text(encoding="utf-8"))
            self.assertNotIn("old", [a["slug"] for a in search])
            self.assertEqual("other\n", (root / "data" / "pending_x_posts.txt").read_text(encoding="utf-8"))

            stub = (root / "articles" / "old.html").read_text(encoding="utf-8")
            self.assertIn('content="noindex, follow"', stub)
            self.assertIn('/articles/best.html', stub)
            self.assertIn("Version complète", stub)
            self.assertEqual("cible", (root / "articles" / "best.html").read_text(encoding="utf-8"))

            second = apply_retirements(root)
            self.assertFalse(second["changed"])

    def test_target_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "articles").mkdir()
            (root / "data" / "articles.json").write_text("[]", encoding="utf-8")
            (root / "data" / "retirements.json").write_text(json.dumps([{
                "slug": "old", "redirect_to": "missing"
            }]), encoding="utf-8")
            with self.assertRaises(ValueError):
                apply_retirements(root)

    def test_retirement_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "articles").mkdir()
            (root / "data" / "articles.json").write_text(json.dumps([
                {"slug": "a", "titre": "A"}, {"slug": "b", "titre": "B"}
            ]), encoding="utf-8")
            (root / "data" / "retirements.json").write_text(json.dumps([
                {"slug": "a", "redirect_to": "b"},
                {"slug": "b", "redirect_to": "a"},
            ]), encoding="utf-8")
            with self.assertRaises(ValueError):
                apply_retirements(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
