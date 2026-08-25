# -*- coding: utf-8 -*-
"""
Test de non-régression SEO — exécuté par deploy.yml après le rebuild.
Échoue (exit 1) si une page requise n'a pas ses balises meta essentielles,
ce qui bloque le déploiement au lieu de publier une page dégradée.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Balises requises par page (regex insensibles à l'ordre des attributs)
REQUIRED = {
    "canonical":    r'<link[^>]+rel="canonical"',
    "og:title":     r'<meta[^>]+property="og:title"',
    "og:image":     r'<meta[^>]+property="og:image"',
    "twitter:card": r'<meta[^>]+name="twitter:card"',
    "description":  r'<meta[^>]+name="description"',
    "lang=fr":      r'<html[^>]+lang="fr"',
}

# Pages statiques à vérifier + le premier article trouvé (représentatif du template)
PAGES = ["index.html", "methode.html", "contact.html", "corrections.html", "archive.html",
         "breves.html"]

# Pages statiques à part : scannées pour le versionnement CSS (le vrai bug du
# 19/08) mais PAS pour les balises meta ci-dessus — 404.html et
# mentions-legales.html en manquent depuis longtemps, un défaut réel mais
# distinct, à traiter séparément plutôt que de bloquer ce déploiement-ci sur
# un problème sans rapport avec ce qu'on corrige aujourd'hui.
PAGES_CACHE_UNIQUEMENT = ["404.html", "cgu.html", "confidentialite.html",
                          "mentions-legales.html", "recherche.html"]

# Classes utilisées volontairement SANS CSS dédiée : tout leur style vient
# d'un attribut style="" en ligne, ou d'une classe parente (.meta, .audio-
# player__ctrl). Vérifié une à une le 04/08 — à ne compléter qu'après
# vérification manuelle du même genre, jamais pour faire taire l'alerte.
CLASSES_HOOK_SANS_CSS = {
    "meta__src", "archive-row", "audio-player__ctrl--stop", "list-section",
    "dossier-serie",  # legacy : 7 vieux articles, plus produit par pipeline.py
}


def check(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8", errors="replace")
    return [name for name, rx in REQUIRED.items() if not re.search(rx, html)]


def style_css_non_versionne(pages_html: list[Path]) -> list[str]:
    """Garde-fou contre la classe du 19/08 : 7 pages statiques écrites à la

    main (contact.html, 404.html, cgu.html, confidentialite.html,
    corrections.html, mentions-legales.html, recherche.html) chargeaient
    src/style.css SANS paramètre de version (?v=2), contrairement aux 14
    pages générées par pipeline.py. Un navigateur ayant déjà visité une de
    ces pages garde en cache l'ANCIENNE feuille de style indéfiniment, même
    après un déploiement qui corrige un vrai défaut visuel — c'était la
    cause de « ça a l'air encore cassé » répété sur contact.html malgré des
    correctifs successifs. Toute page doit référencer style.css avec un
    paramètre de version, jamais une URL nue."""
    sans_version = []
    for path in pages_html:
        html = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r'href="[^"]*style\.css"', html):
            sans_version.append(str(path.relative_to(ROOT)))
    return sans_version


def classes_sans_css(pages_html: list[Path], style_css: str) -> dict[str, list[str]]:
    """Garde-fou contre la classe du 04/08 : `.nav-dropdown` et ses enfants
    étaient utilisés sur les 171 pages article sans AUCUNE règle CSS nulle
    part (ni style.css, ni <style> inline) — le menu s'affichait en liste
    brute, non positionnée, sans fond ni bordure, sur la quasi-totalité du
    site, sans que rien ne le signale avant la lecture manuelle d'un lecteur.

    On extrait les classes réellement définies (sélecteurs simples ET
    listes séparées par des virgules) et on compare à celles utilisées dans
    le HTML. Toute classe qui n'a ni définition globale, ni définition
    inline sur SA PAGE, ni figure dans CLASSES_HOOK_SANS_CSS est un défaut
    potentiel — à vérifier manuellement (cf. cette liste) avant d'ajouter
    une exception, jamais pour la faire disparaître silencieusement."""
    def _classes_definies(css: str) -> set[str]:
        # Un sélecteur avant `{` peut être une liste séparée par virgules
        # (".a, .b, .c { … }") — les considérer une à une, pas comme un bloc.
        classes = set()
        for bloc_selecteur in re.findall(r"([^{}]+)\{", css):
            for sel in bloc_selecteur.split(","):
                classes |= set(re.findall(r"\.([a-zA-Z0-9_-]+)", sel))
        return classes

    classes_globales = _classes_definies(style_css)
    manquantes: dict[str, list[str]] = {}
    for path in pages_html:
        html = path.read_text(encoding="utf-8", errors="replace")
        # `<style[^>]*>` et non `<style>` : la balise porte souvent un attribut.
        #
        # Défaut du 14/08 — ce garde-fou a bloqué le déploiement du premier
        # article publié après neuf jours d'arrêt, en signalant `.cite-ref`
        # « sans CSS trouvée nulle part ». La règle existait pourtant bien dans
        # la page, injectée par la couche vitrine dans un
        # `<style id="lf-citations">` : le motif exigeait une balise nue et ne
        # la voyait pas.
        #
        # Ce n'était donc pas une classe non stylée mais un angle mort du
        # contrôle — et il aurait bloqué TOUS les futurs articles à citations
        # numérotées, format par défaut depuis le 05/08. La bonne correction
        # est ici, jamais dans `CLASSES_HOOK_SANS_CSS` : y inscrire `.cite-ref`
        # aurait fait taire l'alerte en laissant le contrôle aveugle à toute
        # feuille inline portant un attribut.
        inline_css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
        classes_dispo = classes_globales | _classes_definies(inline_css) | CLASSES_HOOK_SANS_CSS
        for classattr in re.findall(r'class="([^"]+)"', html):
            for c in classattr.split():
                # Classes visiblement injectées par un template JS (jamais
                # littérales dans le HTML statique) : faux positifs connus.
                if not c or c in classes_dispo or "+" in c or "${" in c:
                    continue
                manquantes.setdefault(c, []).append(str(path.relative_to(ROOT)))
    return manquantes


def main() -> int:
    targets = [ROOT / p for p in PAGES if (ROOT / p).exists()]
    articles = sorted((ROOT / "articles").glob("*.html"))
    if articles:
        targets.append(articles[0])
        targets.append(articles[-1])

    failures = 0
    for path in targets:
        missing = check(path)
        # L'archive et certaines pages listes n'exigent pas og:image spécifique,
        # mais toutes doivent avoir canonical + description + lang.
        if missing:
            print(f"[SEO FAIL] {path.relative_to(ROOT)} — manquant : {', '.join(missing)}")
            failures += 1
        else:
            print(f"[SEO OK]   {path.relative_to(ROOT)}")

    # Bonus : le mot littéral "None" dans un bloc sources = bug d'affichage
    none_hits = []
    for art in articles:
        txt = art.read_text(encoding="utf-8", errors="replace")
        if re.search(r"·\s*None\s*[·<]", txt):
            none_hits.append(art.name)
    if none_hits:
        print(f"[SEO FAIL] Champ date 'None' affiché dans : {', '.join(none_hits[:5])}"
              + (f" (+{len(none_hits)-5} autres)" if len(none_hits) > 5 else ""))
        failures += 1

    # Garde-fou classes sans CSS (constat 04/08, .nav-dropdown sur 171 pages) —
    # scanné sur les mêmes pages que le reste de ce fichier : les statiques
    # ci-dessus, plus TOUS les articles (le défaut ne touchait qu'eux, et un
    # seul échantillon ne l'aurait pas montré sur toutes les variantes de
    # template).
    style_css_path = ROOT / "src" / "style.css"
    if style_css_path.exists():
        style_css = style_css_path.read_text(encoding="utf-8", errors="replace")
        pages_a_scanner = [p for p in targets] + articles

        pages_cache = [ROOT / p for p in PAGES_CACHE_UNIQUEMENT if (ROOT / p).exists()]
        non_versionnees = style_css_non_versionne(pages_a_scanner + pages_cache)
        if non_versionnees:
            print(f"\n[SEO FAIL] style.css chargé SANS version (cache navigateur "
                  f"permanent) : {', '.join(non_versionnees)}")
            failures += 1

        manquantes = classes_sans_css(pages_a_scanner, style_css)
        if manquantes:
            print(f"\n[SEO FAIL] Classe(s) utilisée(s) sans CSS trouvée nulle part :")
            for c, pages_touchees in sorted(manquantes.items(), key=lambda x: -len(x[1])):
                exemple = pages_touchees[0]
                print(f"    .{c}  — {len(pages_touchees)} page(s), ex. {exemple}")
            print("Si c'est volontaire (style entièrement inline), ajouter la classe "
                  "à CLASSES_HOOK_SANS_CSS dans scripts/check_seo.py — après vérification "
                  "manuelle, jamais pour faire taire cette alerte.")
            failures += 1

    if failures:
        print(f"\n{failures} page(s) en échec — déploiement bloqué.")
        return 1
    print(f"\nToutes les vérifications SEO passent ({len(targets)} pages).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
