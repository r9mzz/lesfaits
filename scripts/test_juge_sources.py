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
    bon_liee = bon_deliee = rate_liee = rate_deliee = sans = 0
    for i, (titre, src, liee) in enumerate(paires, 1):
        v = juger(client, titre, src)
        if v is None:
            sans += 1
            continue
        # Sur une paire DÉLIÉE, « GENERALE » est un demi-échec : le juge n'a pas
        # vu que le document parlait d'autre chose. On ne compte comme réussite
        # que HORS_SUJET.
        if liee:
            bon_liee += v in ("PERTINENTE", "GENERALE")
            rate_liee += v == "HORS_SUJET"
        else:
            bon_deliee += v == "HORS_SUJET"
            rate_deliee += v != "HORS_SUJET"
        if i % 20 == 0:
            print(f"  {i}/{len(paires)}")

    n_liee, n_deliee = bon_liee + rate_liee, bon_deliee + rate_deliee
    print("\n" + "=" * 66)
    print("ÉPREUVE A — le juge distingue-t-il une source de son sujet ?")
    print("=" * 66)
    if n_liee:
        print(f"  source AVEC son article, reconnue liée   : {bon_liee}/{n_liee} "
              f"({100 * bon_liee / n_liee:.0f} %)")
    if n_deliee:
        print(f"  source AVEC un article étranger, rejetée : {bon_deliee}/{n_deliee} "
              f"({100 * bon_deliee / n_deliee:.0f} %)")
    total = n_liee + n_deliee
    if total:
        print(f"  justesse globale : {100 * (bon_liee + bon_deliee) / total:.0f} % "
              f"({sans} sans verdict)")
        print("\n  Repère : 50 % = hasard. Sous 80 %, inutilisable — cette épreuve"
              "\n  est la plus facile des deux, un juge qui échoue ici échouera"
              "\n  a fortiori sur la distinction fine de l'épreuve B.")

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
