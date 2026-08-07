#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

from apply_premium_design import apply, check

ROOT = Path(__file__).resolve().parent.parent
PREMIUM = ROOT / "src" / "premium.css"


def _assert_css_contract() -> None:
    css = PREMIUM.read_text(encoding="utf-8")
    required = (
        "env(safe-area-inset-top",
        "env(safe-area-inset-bottom",
        "@media (display-mode: standalone)",
        ".brand__icon { display: none !important; }",
        ".art__title",
        ".art__h2",
        ".une__main",
        ".nav-expand-item svg { display: none; }",
        "width: calc(100% + 80px) !important;",
        "margin: -36px -40px 22px !important;",
        "width: calc(100% + 40px) !important;",
        "margin: -22px -20px 18px !important;",
        "@media (max-width: 768px)",
    )
    missing = [token for token in required if token not in css]
    assert not missing, f"Contrat CSS premium incomplet: {missing}"
    assert css.count("{") == css.count("}"), "Accolades CSS déséquilibrées"


def _fixture(root: Path, *, with_manifest: bool) -> str:
    (root / "src").mkdir(parents=True)
    (root / "articles").mkdir()
    (root / "categories").mkdir()
    (root / "src" / "premium.css").write_text(PREMIUM.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = '<link rel="manifest" href="/manifest.json"/>\n' if with_manifest else ""
    html = (
        "<!doctype html><html lang=\"fr\"><head>\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{manifest}"
        '<link rel="stylesheet" href="/src/style.css?v=2"/>\n'
        "</head><body><main>Test</main></body></html>\n"
    )
    for path in (root / "index.html", root / "articles" / "a.html", root / "categories" / "science.html"):
        path.write_text(html, encoding="utf-8")
    return html


def _assert_apply_is_idempotent_and_reversible() -> None:
    for with_manifest in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = _fixture(root, with_manifest=with_manifest)

            changed, failures = apply(root)
            assert not failures
            assert changed == 3
            assert not check(root, enabled=True)

            snapshot = {
                path: path.read_text(encoding="utf-8")
                for path in (root / "index.html", root / "articles" / "a.html", root / "categories" / "science.html")
            }
            changed_again, failures = apply(root)
            assert not failures
            assert changed_again == 0, "Une seconde application ne doit créer aucun diff"
            assert snapshot == {
                path: path.read_text(encoding="utf-8")
                for path in snapshot
            }

            changed_remove, failures = apply(root, remove=True)
            assert not failures
            assert changed_remove == 3
            assert not check(root, enabled=False)
            for path in snapshot:
                restored = path.read_text(encoding="utf-8")
                if with_manifest:
                    assert restored == original, "Le rollback doit restaurer le HTML initial exactement"
                else:
                    assert 'data-lf-premium="1"' not in restored
                    assert 'data-lf-app="1"' not in restored
                    assert 'data-lf-app-manifest="1"' not in restored


def main() -> int:
    _assert_css_contract()
    _assert_apply_is_idempotent_and_reversible()
    print("[PREMIUM DESIGN] CSS, app shell, idempotence et rollback : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
