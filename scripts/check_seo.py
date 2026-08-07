# -*- coding: utf-8 -*-
"""Garde-fou de déploiement SEO + intégrité du site statique."""
import re
import sys
from pathlib import Path

from check_site_integrity import run as check_site_integrity
from normalize_corpus_indexing import run as normalize_corpus_indexing
from normalize_publication_metadata import run as normalize_publication_metadata
from normalize_source_metadata import run as normalize_source_metadata
from normalize_visible_publication_time import run as normalize_visible_publication_time

ROOT = Path(__file__).parent.parent

REQUIRED = {
    "canonical": r'<link[^>]+rel="canonical"',
    "og:title": r'<meta[^>]+property="og:title"',
    "og:image": r'<meta[^>]+property="og:image"',
    "twitter:card": r'<meta[^>]+name="twitter:card"',
    "description": r'<meta[^>]+name="description"',
    "lang=fr": r'<html[^>]+lang="fr"',
}
PAGES = ["index.html", "methode.html", "contact.html", "corrections.html", "archive.html", "breves.html"]
CLASSES_HOOK_SANS_CSS = {
    "meta__src", "archive-row", "audio-player__ctrl--stop", "list-section",
    "dossier-serie",
}


def check(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8", errors="replace")
    return [name for name, rx in REQUIRED.items() if not re.search(rx, html)]


def classes_sans_css(pages_html: list[Path], style_css: str) -> dict[str, list[str]]:
    def _classes_definies(css: str) -> set[str]:
        classes: set[str] = set()
        for bloc_selecteur in re.findall(r"([^{}]+)\{", css):
            for sel in bloc_selecteur.split(","):
                classes |= set(re.findall(r"\.([a-zA-Z0-9_-]+)", sel))
        return classes
    classes_globales = _classes_definies(style_css)
    manquantes: dict[str, list[str]] = {}
    for path in pages_html:
        html = path.read_text(encoding="utf-8", errors="replace")
        inline_css = "".join(re.findall(r"<style>(.*?)</style>", html, re.S))
        classes_dispo = classes_globales | _classes_definies(inline_css) | CLASSES_HOOK_SANS_CSS
        for classattr in re.findall(r'class="([^"]+)"', html):
            for css_class in classattr.split():
                if not css_class or css_class in classes_dispo or "+" in css_class or "${" in css_class:
                    continue
                manquantes.setdefault(css_class, []).append(str(path.relative_to(ROOT)))
    return manquantes


def _run_normalizer(label: str, fn) -> int:
    try:
        changed, errors = fn(check=False)
        if errors:
            for error in errors[:10]:
                print(f"[SEO FAIL] {label} — {error}")
            return 1
        _, check_errors = fn(check=True)
        if check_errors:
            for error in check_errors[:10]:
                print(f"[SEO FAIL] {label} — {error}")
            return 1
        print(f"[SEO OK]   {label} cohérentes ({changed} correction(s))")
        return 0
    except Exception as exc:
        print(f"[SEO FAIL] {label} — {exc}")
        return 1


def main() -> int:
    failures = 0
    failures += _run_normalizer("Métadonnées publication", normalize_publication_metadata)
    failures += _run_normalizer("Heures visibles", normalize_visible_publication_time)
    failures += _run_normalizer("Métadonnées sources", normalize_source_metadata)
    failures += _run_normalizer("Indexation corpus", normalize_corpus_indexing)

    targets = [ROOT / p for p in PAGES if (ROOT / p).exists()]
    articles = sorted((ROOT / "articles").glob("*.html"))
    if articles:
        targets.extend([articles[0], articles[-1]])

    for path in targets:
        missing = check(path)
        if missing:
            print(f"[SEO FAIL] {path.relative_to(ROOT)} — manquant : {', '.join(missing)}")
            failures += 1
        else:
            print(f"[SEO OK]   {path.relative_to(ROOT)}")

    none_hits = []
    for art in articles:
        txt = art.read_text(encoding="utf-8", errors="replace")
        if re.search(r"·\s*None\s*[·<]", txt):
            none_hits.append(art.name)
    if none_hits:
        print("[SEO FAIL] Champ date 'None' affiché dans : " + ", ".join(none_hits[:5]))
        failures += 1

    style_css_path = ROOT / "src" / "style.css"
    if style_css_path.exists():
        style_css = style_css_path.read_text(encoding="utf-8", errors="replace")
        manquantes = classes_sans_css(targets + articles, style_css)
        if manquantes:
            print("\n[SEO FAIL] Classe(s) utilisée(s) sans CSS trouvée nulle part :")
            for css_class, pages_touchees in sorted(manquantes.items(), key=lambda x: -len(x[1])):
                print(f"    .{css_class} — {len(pages_touchees)} page(s), ex. {pages_touchees[0]}")
            failures += 1

    integrity_errors = check_site_integrity()
    if integrity_errors:
        print("\n[SEO FAIL] Intégrité du site :")
        for error in integrity_errors[:30]:
            print(f"    {error}")
        if len(integrity_errors) > 30:
            print(f"    +{len(integrity_errors)-30} autre(s)")
        failures += 1
    else:
        print("[SEO OK]   Intégrité globale : liens/assets/canonical/images/sources/IDs/newsletter/corpus")

    if failures:
        print(f"\n{failures} contrôle(s) en échec — déploiement bloqué.")
        return 1
    print(f"\nToutes les vérifications passent ({len(targets)} pages SEO + corpus complet).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
