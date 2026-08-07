#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Applique ou retire la couche visuelle Premium Les Faits.

Le design historique n'est jamais réécrit : cette commande ajoute uniquement
un second stylesheet et des métadonnées d'affichage app identifiables. Le mode
``--remove`` retire exactement ces ajouts, ce qui rend le retour arrière sûr.

La commande accepte ``--root`` pour agir soit sur le dépôt source pendant les
tests, soit sur le clone public ``lesfaits-site`` dans GitHub Actions.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PREMIUM_HREF = "/src/premium.css?v=1"
PREMIUM_LINK = f'<link rel="stylesheet" href="{PREMIUM_HREF}" data-lf-premium="1"/>'
MANAGED_MANIFEST = '<link rel="manifest" href="/manifest.json" data-lf-app-manifest="1"/>'

APP_META = (
    '<meta name="theme-color" content="#F0EDE6" media="(prefers-color-scheme: light)" data-lf-app="1"/>\n'
    '<meta name="theme-color" content="#131210" media="(prefers-color-scheme: dark)" data-lf-app="1"/>\n'
    '<meta name="mobile-web-app-capable" content="yes" data-lf-app="1"/>\n'
    '<meta name="apple-mobile-web-app-capable" content="yes" data-lf-app="1"/>\n'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default" data-lf-app="1"/>\n'
    '<meta name="apple-mobile-web-app-title" content="Les Faits" data-lf-app="1"/>'
)

PREMIUM_LINK_RE = re.compile(
    r"\s*<link\b[^>]*data-lf-premium=[\"']1[\"'][^>]*?/?>\s*",
    re.IGNORECASE,
)
APP_META_RE = re.compile(
    r"\s*<meta\b[^>]*data-lf-app=[\"']1[\"'][^>]*?/?>\s*",
    re.IGNORECASE,
)
MANAGED_MANIFEST_RE = re.compile(
    r"\s*<link\b[^>]*data-lf-app-manifest=[\"']1[\"'][^>]*?/?>\s*",
    re.IGNORECASE,
)
BASE_STYLESHEET_RE = re.compile(
    r'(<link\b[^>]*rel=["\']stylesheet["\'][^>]*href=["\']/src/style\.css[^"\']*["\'][^>]*?/?>)',
    re.IGNORECASE,
)
MANIFEST_RE = re.compile(
    r'(<link\b[^>]*rel=["\']manifest["\'][^>]*?/?>)',
    re.IGNORECASE,
)
HEAD_END_RE = re.compile(r"</head>", re.IGNORECASE)


def html_targets(root: Path) -> list[Path]:
    targets: list[Path] = []
    for pattern in ("*.html", "articles/*.html", "categories/*.html"):
        targets.extend(root.glob(pattern))
    return sorted({p.resolve() for p in targets if p.is_file()})


def _remove_managed_markup(html: str) -> str:
    html = PREMIUM_LINK_RE.sub("\n", html)
    html = APP_META_RE.sub("\n", html)
    html = MANAGED_MANIFEST_RE.sub("\n", html)
    # Évite l'accumulation de lignes vides après plusieurs bascules on/off.
    return re.sub(r"\n{3,}", "\n\n", html)


def _inject(html: str) -> str:
    html = _remove_managed_markup(html)

    style = BASE_STYLESHEET_RE.search(html)
    if style:
        pos = style.end()
        html = html[:pos] + "\n  " + PREMIUM_LINK + html[pos:]
    else:
        head_end = HEAD_END_RE.search(html)
        if not head_end:
            raise RuntimeError("document HTML sans </head>")
        pos = head_end.start()
        html = html[:pos] + "  " + PREMIUM_LINK + "\n" + html[pos:]

    manifest = MANIFEST_RE.search(html)
    if not manifest:
        head_end = HEAD_END_RE.search(html)
        if not head_end:
            raise RuntimeError("document HTML sans </head>")
        pos = head_end.start()
        html = html[:pos] + "  " + MANAGED_MANIFEST + "\n" + html[pos:]
        manifest = MANIFEST_RE.search(html)

    if not manifest:
        raise RuntimeError("impossible d'injecter le manifest")
    pos = manifest.start()
    html = html[:pos] + APP_META + "\n  " + html[pos:]
    return html


def apply(root: Path, *, remove: bool = False) -> tuple[int, list[str]]:
    premium = root / "src" / "premium.css"
    if not remove and not premium.exists():
        raise RuntimeError(f"Feuille premium absente : {premium}")

    changed = 0
    failures: list[str] = []
    for path in html_targets(root):
        original = path.read_text(encoding="utf-8", errors="replace")
        try:
            updated = _remove_managed_markup(original) if remove else _inject(original)
        except RuntimeError as exc:
            failures.append(f"{path.relative_to(root)}: {exc}")
            continue
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed, failures


def check(root: Path, *, enabled: bool = True) -> list[str]:
    failures: list[str] = []
    premium = root / "src" / "premium.css"
    if enabled and not premium.exists():
        failures.append("src/premium.css absent")

    targets = html_targets(root)
    if not targets:
        failures.append("aucune page HTML trouvée")
        return failures

    for path in targets:
        html = path.read_text(encoding="utf-8", errors="replace")
        link_count = len(PREMIUM_LINK_RE.findall(html))
        meta_count = len(APP_META_RE.findall(html))
        manifest_count = len(MANIFEST_RE.findall(html))
        rel = path.relative_to(root)
        if enabled:
            if link_count != 1:
                failures.append(f"{rel}: {link_count} lien(s) premium, attendu 1")
            if meta_count != 6:
                failures.append(f"{rel}: {meta_count} meta app, attendu 6")
            if manifest_count < 1:
                failures.append(f"{rel}: manifest absent")
        else:
            if link_count:
                failures.append(f"{rel}: lien premium encore présent")
            if meta_count:
                failures.append(f"{rel}: meta app encore présente")
            if MANAGED_MANIFEST_RE.search(html):
                failures.append(f"{rel}: manifest géré encore présent")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Racine du site à modifier")
    parser.add_argument("--remove", action="store_true", help="Retirer la couche Premium")
    parser.add_argument("--check", action="store_true", help="Vérifier sans modifier")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.check:
        failures = check(root, enabled=not args.remove)
        if failures:
            print("[DESIGN FAIL]")
            for item in failures[:30]:
                print(" -", item)
            if len(failures) > 30:
                print(f" - ... +{len(failures) - 30} autre(s)")
            return 1
        print(f"[DESIGN OK] {len(html_targets(root))} page(s) cohérentes.")
        return 0

    changed, failures = apply(root, remove=args.remove)
    if failures:
        print("[DESIGN FAIL]")
        for item in failures[:30]:
            print(" -", item)
        return 1
    action = "retirée" if args.remove else "appliquée"
    print(f"[DESIGN] Couche Premium {action} sur {changed} page(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
