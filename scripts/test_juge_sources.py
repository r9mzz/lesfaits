# -*- coding: utf-8 -*-
"""BACKTEST — un petit modèle sait-il dire qu'une source ne parle pas du sujet ?

C'est le levier numéro un de l'audit du 12/08, et le seul qui ne soit pas
implémenté : refuser une page permanente qui ne traite pas le sujet de
l'article. Cas d'école, `articles/rougeole-antiviral-etude.html` — le titre
promet un antiviral à l'étude, et les sources sont la fiche « Rougeole » de
l'OMS, la page « Données » de Santé publique France, « Rougeole » de l'Inserm.
Des documents authentiques, sérieux, et qui ne parlent pas du sujet.

POURQUOI CE JUGE-LÀ ET PAS CELUI DES SUJETS. Le backtest du juge de sujet
(`test_juge_sujet.py`, 12/08) a rendu 50 % sur un jeu équilibré, soit le
hasard — et il a montré au passage que notre référence était fausse. « Ce
sujet mérite-t-il un article ? » est un jugement éditorial, non vérifiable.
« Ce document traite-t-il de ce sujet ? » est une question factuelle : elle a
une bonne réponse, et un humain peut trancher le désaccord.

DEUX ÉPREUVES, dans cet ordre :

  A — DISCRIMINATION (référence objective, construite sans étiquetage humain).
      Chaque source réellement citée par un article est présentée deux fois :
      avec SON article (attendu : pertinente), puis avec un article tiré au
      hasard sur un autre sujet (attendu : hors sujet). Un juge incapable de
      passer cette épreuve triviale est inutilisable, la suite est sans objet.

  B — APPLICATION sur le cas d'école. Verdicts détaillés sur les 6 sources de
      l'article rougeole, à relire à la main. C'est là qu'on voit si le juge
      distingue le document daté de la page encyclopédique permanente.

⚠ Le juge ne voit que l'institution, le titre du document et son URL — ce que
le pipeline connaît au moment de choisir. Il ne télécharge rien.

⚠ Ne tourne pas dans le sandbox (api.groq.com injoignable). Lancer via
.github/workflows/juge_sources.yml.

    python scripts/test_juge_sources.py --limite 30
"""
import argparse
import glob
import html as htmlmod
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8")
RACINE = Path(__file__).resolve().parent.parent

MODELE = os.getenv("JUGE_MODELE", "llama-3.1-8b-instant")

PROMPT = """Tu vérifies si un document peut servir de source à un article de presse.

On te donne le TITRE de l'article, puis un DOCUMENT (institution, titre, URL).

Question unique : ce document traite-t-il du sujet PRÉCIS de l'article, ou
seulement de son thème général ?

Réponds PERTINENTE si le document porte sur l'événement, l'étude, la décision
ou le chiffre précis annoncé par le titre de l'article.

Réponds GENERALE si le document ne traite que du thème large — une fiche
encyclopédique, une page « données » permanente, un portail de rubrique, un
dossier de fond — sans porter sur le fait précis de l'article.

Réponds HORS_SUJET si le document parle d'autre chose.

Un seul mot : PERTINENTE, GENERALE ou HORS_SUJET."""


def txt(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()


def charger_articles() -> list[dict]:
    """(titre, [sources]) pour chaque article publié ayant un bloc SOURCES."""
    out = []
    for f in sorted(glob.glob(str(RACINE / "articles" / "*.html"))):
        h = Path(f).read_text(encoding="utf-8", errors="ignore")
        i = h.find('class="sources"')
        if i < 0:
            continue
        m = re.search(r'<h1[^>]*class="art__title"[^>]*>(.*?)</h1>', h, re.S)
        if not m:
            continue
        items = re.findall(
            r'<li>.*?<(?:cite|strong)>(.*?)</(?:cite|strong)>\s*·\s*<em>(.*?)</em>.*?href="(.*?)"',
            h[i:i + 12000], re.S)
        srcs = [{"institution": txt(a), "titre": txt(b), "url": c} for a, b, c in items]
        if srcs:
            out.append({"slug": Path(f).stem, "titre": txt(m.group(1)), "sources": srcs})
    return out


def decrire(s: dict) -> str:
    chemin = urlparse(s["url"]).path or "/"
    return (f"institution : {s['institution']}\n"
            f"titre du document : {s['titre']}\n"
            f"adresse : {urlparse(s['url']).netloc}{chemin}")


def juger(client, titre_article: str, source: dict) -> str | None:
    contenu = f"ARTICLE : {titre_article}\n\nDOCUMENT :\n{decrire(source)}"
    for tentative in range(4):
        try:
            r = client.chat.completions.create(
                model=MODELE,
                messages=[{"role": "system", "content": PROMPT},
                          {"role": "user", "content": contenu}],
                temperature=0, max_tokens=6)
            mot = (r.choices[0].message.content or "").strip().upper()
            for v in ("HORS_SUJET", "HORS SUJET", "GENERALE", "PERTINENTE"):
                if v in mot:
                    return "HORS_SUJET" if v.startswith("HORS") else v
            return None
        except Exception as e:  # noqa: BLE001
            if "rate" in str(e).lower() or "429" in str(e):
                time.sleep(20 * (tentative + 1))
                continue
            print(f"    erreur : {type(e).__name__} {str(e)[:110]}")
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=30,
                    help="nombre de paires par épreuve")
    args = ap.parse_args()

    arts = charger_articles()
    print(f"{len(arts)} articles publiés avec sources\n")
    try:
        from groq import Groq
    except ImportError:
        print("ERREUR : paquet groq absent.")
        return 1
    if not os.getenv("GROQ_API_KEY"):
        print("ERREUR : GROQ_API_KEY absent — lancer depuis le runner GitHub.")
        return 1
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # ── ÉPREUVE A ────────────────────────────────────────────────────────────
    random.seed(12)
    paires = []
    for a in random.sample(arts, min(args.limite, len(arts))):
        s = random.choice(a["sources"])
        paires.append((a["titre"], s, True))
        autre = random.choice([x for x in arts if x["slug"] != a["slug"]])
        paires.append((autre["titre"], s, False))
    random.shuffle(paires)

    print(f"ÉPREUVE A — discrimination, {len(paires)} paires, modèle {MODELE}")
    # Répartition COMPLÈTE des trois verdicts de chaque côté. La première
    # version de ce test ne comptait « réussi » sur une paire déliée que le
    # verdict HORS_SUJET, en acceptant GENERALE du côté lié : deux règles
    # différentes pour la même sortie, donc un pourcentage global qui ne
    # mesurait rien. C'est la répartition brute qui permet de choisir la règle
    # d'exploitation, pas l'inverse.
    from collections import Counter
    rep = {True: Counter(), False: Counter()}
    sans = 0
    for i, (titre, src, liee) in enumerate(paires, 1):
        v = juger(client, titre, src)
        if v is None:
            sans += 1
            continue
        rep[liee][v] += 1
        if i % 20 == 0:
            print(f"  {i}/{len(paires)}")

    print("\n" + "=" * 66)
    print("ÉPREUVE A — répartition des verdicts")
    print("=" * 66)
    print(f"  {'':<26}{'PERTINENTE':>12}{'GENERALE':>11}{'HORS_SUJET':>12}")
    for liee, libelle in ((True, "source ↔ SON article"), (False, "source ↔ article étranger")):
        c = rep[liee]
        n = sum(c.values()) or 1
        print(f"  {libelle:<26}{c['PERTINENTE']:>12}{c['GENERALE']:>11}{c['HORS_SUJET']:>12}"
              f"   (n={n})")

    # Règle d'exploitation envisagée : on écarte tout ce qui n'est pas
    # PERTINENTE. C'est celle qui répare le défaut de l'article rougeole.
    garde_liee = rep[True]["PERTINENTE"]
    n_liee = sum(rep[True].values()) or 1
    ecarte_deliee = sum(rep[False].values()) - rep[False]["PERTINENTE"]
    n_deliee = sum(rep[False].values()) or 1
    print("\n  Si la règle est « on n'accepte que PERTINENTE » :")
    print(f"    vraies sources conservées      : {garde_liee}/{n_liee} "
          f"({100 * garde_liee / n_liee:.0f} %)")
    print(f"    sources étrangères écartées    : {ecarte_deliee}/{n_deliee} "
          f"({100 * ecarte_deliee / n_deliee:.0f} %)")
    print(f"    ⚠ vraies sources perdues       : {n_liee - garde_liee}"
          f"  ({100 * (n_liee - garde_liee) / n_liee:.0f} %)")
    print(f"  ({sans} paires sans verdict exploitable)")
    print("\n  LECTURE : le chiffre qui décide est celui des vraies sources")
    print("  perdues. Un article publié sur 3 sources n'en a pas à sacrifier.")

    # ── ÉPREUVE B ────────────────────────────────────────────────────────────
    cas = next((a for a in arts if a["slug"] == "rougeole-antiviral-etude"), None)
    if cas:
        print("\n" + "=" * 66)
        print("ÉPREUVE B — cas d'école : " + cas["titre"][:52])
        print("=" * 66)
        print("  Attendu à la lecture humaine : seule la source d'origine")
        print("  (Sciences et Avenir) traite de l'antiviral ; les autres sont")
        print("  des pages permanentes sur la rougeole en général.\n")
        for s in cas["sources"]:
            v = juger(client, cas["titre"], s) or "—"
            marque = "✓" if v in ("GENERALE", "HORS_SUJET") else " "
            print(f"  {marque} {v:<11} {s['institution'][:22]:<24} {s['titre'][:40]}")
        print("\n  ✓ = le juge aurait écarté cette source.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
