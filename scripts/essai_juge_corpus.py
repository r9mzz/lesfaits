# -*- coding: utf-8 -*-
"""Le juge Mistral recale-t-il nos MEILLEURS articles de l'ère Llama ?

── LA QUESTION, ET POURQUOI ELLE BLOQUE TOUT LE RESTE ────────────────────────

Depuis le passage à Mistral, les runs finissent sur `[REJET QUALITÉ] N
bloquant(s) après 3 passes`. Run du 20/08, 10 sujets recalés, 37 occurrences :

    9 chiffre_errone · 8 niveau_preuve_insuffisant · 6 annonce_perimee
    5 incoherence_inter_sections · 5 source_inventee · 4 accusation_...

Deux lectures tiennent également debout, et elles appellent des correctifs
OPPOSÉS :

    A. le rédacteur Mistral commet de vraies erreurs      → corriger le PROMPT
    B. le juge Mistral est plus sévère que Llama          → discuter ses SEUILS

On ne peut pas les départager sur les runs, parce qu'on a changé le rédacteur
ET le juge dans le même mouvement — l'erreur de méthode que ce projet a déjà
payée sur la comparaison brève/actu après le 05/08.

Ce script tient la variable manquante fixe : le TEXTE. Il fait relire par le
juge actuel des articles écrits par Llama, déjà publiés, et dont le
fact-checker de l'époque n'avait signalé AUCUN problème.

    juge recale nos meilleurs   →  hypothèse B, le juge a durci
    juge les valide             →  hypothèse A, la rédaction a faibli

── CE QUE « MEILLEURS » VEUT DIRE ICI, ET POURQUOI CE N'EST PAS UN AVIS ──────

`conforme_du_premier_coup` est la seule définition MESURABLE dont on dispose :
l'article a passé le fact-check Llama sans un seul problème détecté. Il y en a
22 sur 251 vérifications (0,8 %), dont 17 réellement présents dans `articles/`.

⚠ Le piège documenté : ce statut ne signifie PAS « publié ». On croise donc
avec les fichiers réellement sur disque, jamais avec le journal seul.

Ce script N'ÉCRIT RIEN, ne publie rien, ne touche à aucun article.

    python scripts/essai_juge_corpus.py            # tout le lot
    python scripts/essai_juge_corpus.py --max 5    # échantillon
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import unescape
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RACINE = Path(__file__).resolve().parent.parent
LOG = RACINE / "data" / "verification_log.json"
ARTICLES = RACINE / "articles"

_LIBELLES = {"faits", "contexte", "nuances", "débats et nuances"}


def _texte(html: str) -> str:
    """HTML → texte brut, sans les appels de citation."""
    html = re.sub(r"<sup class=\"cite-ref\".*?</sup>", " ", html, flags=re.S)
    return unescape(re.sub(r"<[^>]+>", " ", html)).replace("\xa0", " ").strip()


def lire_article(slug: str) -> dict | None:
    """Reconstruit l'article depuis le HTML publié.

    On lit le rendu plutôt qu'un JSON d'origine parce que c'est le seul état
    qui existe encore : `articles.json` ne garde que le chapeau et les compteurs.
    C'est aussi le texte que le lecteur a réellement sous les yeux — donc
    exactement ce qu'on veut soumettre au juge.
    """
    f = ARTICLES / f"{slug}.html"
    if not f.exists():
        return None
    h = f.read_text(encoding="utf-8")

    titre = _texte(m.group(1)) if (m := re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)) else slug
    resume = _texte(m.group(1)) if (m := re.search(
        r'<p class="art__resume">(.*?)</p>', h, re.S)) else ""

    # Les intertitres sont ÉDITORIAUX depuis le 05/08 (« Le chiffre de la nuit »
    # plutôt que « Les faits ») : on ne peut donc pas retrouver les sections par
    # leur nom. On les prend dans l'ORDRE d'apparition, qui lui n'a pas changé.
    # ⚠ Certains de ces articles n'ont qu'UNE section : ce sont des formats
    # courts, ou des articles d'avant les intertitres éditoriaux. Les trois
    # clés existent toujours, éventuellement vides — le fact-checker sait
    # traiter une section absente, il ne sait pas traiter une clé manquante.
    blocs = re.split(r'<h2 class="art__h2">.*?</h2>', h, flags=re.S)[1:]
    corps = {"faits": "", "contexte": "", "nuances": ""}
    for cle, bloc in zip(("faits", "contexte", "nuances"), blocs):
        bloc = re.split(r'<section[^>]*aria-label="Sources"', bloc, flags=re.S)[0]
        bloc = re.split(r'<div class="art__(?!h2)', bloc, flags=re.S)[0]
        corps[cle] = _texte(bloc)

    # ⚠ Le markup des sources a CHANGÉ le 05/08 : `id="source-n"` est né avec
    # les citations numérotées. Les articles antérieurs — c'est-à-dire la
    # plupart de nos « meilleurs » — n'ont que `<li><cite>…`. Ancrer
    # l'extraction sur l'identifiant n'aurait rendu QU'UN article sur 17, et
    # le test aurait mesuré la version du template au lieu du juge.
    bloc_src = re.split(r'<section[^>]*aria-label="Sources"', h, flags=re.S)
    sources = []
    if len(bloc_src) > 1:
        for m in re.finditer(r"<li[^>]*>(.*?)</li>", bloc_src[1], re.S):
            lien = re.search(r'href="([^"]+)"', m.group(1))
            sources.append({"url": lien.group(1) if lien else "",
                            "titre": _texte(m.group(1))[:200],
                            "institution": ""})
    if not corps.get("faits") or not sources:
        return None
    return {"titre": titre, "resume": [resume], "corps": corps, "sources": sources}


def format_publie(slug: str) -> str:
    """« brève » ou « actu », lu dans articles.json.

    ⚠ Indispensable, pas cosmétique. La médiane de longueur de ces articles est
    de 126 mots : beaucoup sont des BRÈVES. Le fact-checker reçoit un préambule
    différent selon le format — sans lui, il signale l'absence de contexte et
    de nuances comme un défaut, et le test serait truqué CONTRE les articles de
    l'ère Llama. On mesurerait la sévérité du juge sur un format que le texte
    n'a jamais prétendu être.

    Les entrées antérieures au 02/08 n'ont pas de champ `format` : absence =
    article, comme partout ailleurs dans le projet.
    """
    try:
        data = json.loads((RACINE / "data" / "articles.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "actu"
    entrees = data.get("articles", data) if isinstance(data, dict) else data
    for a in entrees:
        if isinstance(a, dict) and a.get("slug") == slug:
            return "breve" if a.get("format") == "breve" else "actu"
    return "actu"


def meilleurs_slugs() -> list[str]:
    """Les articles passés au fact-check Llama SANS aucun problème détecté."""
    entrees = json.loads(LOG.read_text(encoding="utf-8"))
    vus, out = set(), []
    for e in entrees:
        if not isinstance(e, dict) or e.get("statut") != "conforme_du_premier_coup":
            continue
        s = e.get("slug")
        # ⚠ `conforme_du_premier_coup` ne veut PAS dire « publié » : trois
        # articles ont ce statut sans exister dans articles/. On ne compte que
        # les fichiers réellement présents.
        if s and s not in vus and (ARTICLES / f"{s}.html").exists():
            vus.add(s)
            out.append(s)
    return out


def meilleures_actus(exclure: set[str], n: int = 7) -> list[str]:
    """Nos meilleures ACTUS : publiées, format long, le moins de problèmes.

    ⚠ Pourquoi ce second groupe est nécessaire. Sur les 16 articles
    `conforme_du_premier_coup` lisibles, 13 sont des BRÈVES et 3 seulement des
    actus. Or les runs actuels produisent des actus. Comparer un juge sévère sur
    des actus à un juge indulgent sur des brèves ne dirait rien : une brève a
    beaucoup moins d'affirmations à vérifier, donc beaucoup moins de prises.

    Le critère reste MESURÉ — `problemes_initiaux` le plus bas — et non un avis
    sur la qualité. Ces articles ont eu des problèmes, contrairement au premier
    groupe : ce sont « nos meilleures actus », pas « des actus parfaites », et
    le rapport les affiche séparément pour qu'on ne mélange pas les deux.
    """
    entrees = json.loads(LOG.read_text(encoding="utf-8"))
    cands = []
    for e in entrees:
        if not isinstance(e, dict):
            continue
        s_ = e.get("slug")
        pb = e.get("problemes_initiaux")
        if (not s_ or s_ in exclure or pb is None
                or e.get("article_type") == "breve"
                or not (ARTICLES / f"{s_}.html").exists()):
            continue
        cands.append((int(pb), s_))
    vus, out = set(), []
    for _, s_ in sorted(cands):
        if s_ not in vus:
            vus.add(s_)
            out.append(s_)
        if len(out) >= n:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="limiter l'échantillon")
    args = ap.parse_args()

    slugs = meilleurs_slugs()
    slugs += meilleures_actus(set(slugs))
    if args.max:
        slugs = slugs[:args.max]
    if not slugs:
        print("Aucun article conforme_du_premier_coup présent sur disque.")
        return 0

    import verification as V
    modele = getattr(V, "GROQ_MODEL", "?")
    print("=" * 76)
    print(f"RELECTURE DE NOS MEILLEURS ARTICLES — juge actuel : {modele}")
    print(f"{len(slugs)} article(s) écrits par Llama, fact-checkés sans AUCUN")
    print("problème à l'époque. Aucun n'est modifié ni republié.")
    print("=" * 76)

    total_pb, recales, lus = 0, 0, 0
    echecs: list[tuple[str, str]] = []
    motifs: dict[str, int] = {}
    for slug in slugs:
        art = lire_article(slug)
        if art is None:
            print(f"\n  {slug[:52]:54} (illisible — ignoré)")
            continue
        fmt = format_publie(slug)
        try:
            rapport = V.detecter(art, article_type=fmt)
        except Exception as e:  # noqa: BLE001
            # ⚠ NE PAS compter cet article. Première version : `lus` était
            # incrémenté AVANT l'appel, si bien que 21 échecs d'API sur 22 ont
            # produit « 0/22 de nos MEILLEURS articles seraient recalés » —
            # une conclusion nette et entièrement fausse. Un instrument de
            # mesure qui confond « aucun problème » et « aucune réponse » est
            # pire que pas d'instrument du tout.
            echecs.append((slug, f"{type(e).__name__}: {str(e)[:70]}"))
            print(f"\n  ⚠ ERREUR  {slug[:44]:46} {type(e).__name__}: {str(e)[:60]}")
            continue
        lus += 1
        pbs = rapport.get("problemes") or []
        blocs = [p for p in pbs if p.get("gravite") in ("bloquant", "majeur")]
        total_pb += len(pbs)
        recales += 1 if blocs else 0
        for p in pbs:
            motifs[p.get("type", "?")] = motifs.get(p.get("type", "?"), 0) + 1
        etat = "❌ RECALÉ" if blocs else "✅ validé"
        print(f"\n  {etat}  [{fmt:5}] {slug[:38]:40} {len(pbs):2} problème(s), "
              f"{len(blocs)} bloquant(s)")
        for p in blocs[:2]:
            print(f"        └ {p.get('type')} : {str(p.get('description'))[:88]}")

    if echecs:
        print(f"\n  ⚠ {len(echecs)} article(s) n'ont PAS pu être jugés — ils sont")
        print("    exclus du calcul, jamais comptés comme validés.")
        print(f"    Première cause : {echecs[0][1]}")
    if not lus:
        print("\n" + "=" * 76)
        print("AUCUN article n'a pu être jugé — ce run ne dit RIEN sur le juge.")
        print("Ne pas lire ce résultat comme « le juge valide tout ».")
        print("=" * 76)
        return 1

    print("\n" + "=" * 76)
    print(f"RÉSULTAT : {recales}/{lus} de nos MEILLEURS articles seraient recalés")
    print(f"           {total_pb} problèmes au total, soit {total_pb / lus:.1f} par article")
    print("           (le fact-checker de l'époque en avait trouvé ZÉRO)")
    print("=" * 76)
    for k, v in sorted(motifs.items(), key=lambda kv: -kv[1])[:8]:
        print(f"   {v:3}  {k}")
    print()
    print("  Lecture — et s'y tenir, c'est tout l'intérêt d'avoir fixé le texte :")
    print("   • beaucoup de recalés → le JUGE a durci. Discuter ses seuils, pas")
    print("     le prompt de rédaction. Et ne PAS les baisser sans regarder si")
    print("     les problèmes signalés sont réels : un juge sévère qui a raison")
    print("     reste un bon juge, et la charte dit qu'on préfère ne rien publier.")
    print("   • peu de recalés → le juge est stable, donc c'est la RÉDACTION")
    print("     Mistral qui produit ces défauts. C'est le prompt qu'il faut")
    print("     adapter, en commençant par les marqueurs d'incertitude.")
    print()
    print("  ⚠ n est petit et l'échantillon est BIAISÉ par construction : ce sont")
    print("  les articles qu'un juge a déjà validés. C'est voulu — on cherche un")
    print("  écart FLAGRANT, pas un taux. Un résultat serré ne conclut rien.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
