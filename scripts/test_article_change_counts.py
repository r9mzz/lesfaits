# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from article_change_counts import count_article_changes


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class ArticleChangeCountTests(unittest.TestCase):
    def test_counts_only_real_article_html_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "articles").mkdir()
            (repo / "data").mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.com")

            (repo / "articles" / "ancien.html").write_text("ancien", encoding="utf-8")
            (repo / "articles" / "a-retirer.html").write_text("retirer", encoding="utf-8")
            (repo / "data" / "articles.json").write_text("[]", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "base")

            (repo / "articles" / "ancien.html").write_text("ancien modifié", encoding="utf-8")
            (repo / "articles" / "nouveau.html").write_text("nouveau", encoding="utf-8")
            (repo / "articles" / "note.txt").write_text("pas un article", encoding="utf-8")
            (repo / "data" / "articles.json").write_text("[{}]", encoding="utf-8")
            (repo / "articles" / "a-retirer.html").unlink()
            git(repo, "add", "-A")

            self.assertEqual(
                count_article_changes(repo, cached=True),
                {"added": 1, "modified": 1, "deleted": 1},
            )

    def test_can_compare_two_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "articles").mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.com")
            (repo / "articles" / "a.html").write_text("a", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "base")
            base = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            (repo / "articles" / "b.html").write_text("b", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-m", "suite")
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()

            self.assertEqual(
                count_article_changes(repo, cached=False, base=base, head=head),
                {"added": 1, "modified": 0, "deleted": 0},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
