# -*- coding: utf-8 -*-
"""MESURE — le clustering d'événements ferait-il mieux que le barème actuel ?

Ne modifie rien. Collecte les flux RSS une fois, puis compare deux tris du
MÊME corpus :

  A. ce que le pipeline sélectionne aujourd'hui (`score_editorial` +
     `selectionner_meilleurs`), qui note la FORME du candidat ;
  B. les grappes d'événements — combien de médias distincts couvrent le même
     fait — qui mesurent l'IMPORTANCE présumée du sujet.

Hypothèse testée : si les deux listes se ressemblent, le clustering n'apporte
rien et l'idée est abandonnée. Si les grappes font remonter des faits que le
barème a ratés, on tient le levier sur `angle_insuffisant` (64 % des rejets
qualité) et sur le manque de sources indépendantes (69 % des articles publiés
n'ont aucune source primaire).

    python scripts/mesure_clustering.py            # collecte réelle
    python scripts/mesure_clustering.py --seuils   # sensibilité au seuil

Aucun token Groq, aucun appel DuckDuckGo : uniquement les flux RSS.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402

# Mots vides + vocabulaire journalistique trop courant pour distinguer un
# sujet. Volontairement court : l'IDF calculée sur la collecte du jour fait
# déjà l'essentiel du travail, cette liste ne sert qu'aux cas les plus francs.
STOP = {
    "dans", "pour", "avec", "sans", "plus", "moins", "leur", "leurs", "cette",
    "ces", "son", "ses", "une", "des", "les", "aux", "par", "sur", "que", "qui",
    "quoi", "dont", "mais", "donc", "cet", "est", "sont", "ete", "etre", "avoir",
    "apres", "avant", "entre", "chez", "vers", "contre", "selon", "comme",
    "tout", "tous", "toute", "toutes", "encore", "deja", "aussi", "faire",
    "fait", "faits", "peut", "peuvent", "va", "vont", "ans", "annee", "annees",
}


def norm_tokens(titre: str) -> set[str]:
    t = unicodedata.normalize("NFD", titre or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return {m for m in re.findall(r"[a-z0-9]+", t) if len(m) >= 4 and m not in STOP}


def collecter() -> list[dict]:
    """Collecte brute, SANS la déduplication par titre du pipeline — c'est
    précisément elle qui détruit le signal qu'on veut mesurer."""
    items: list[dict] = []
    vus_url: set[str] = set()
    print(f"[COLLECTE] {len(P.RSS_SOURCES)} flux…")
    for src in P.RSS_SOURCES:
        try:
            lot = P.fetch_rss(src)
        except Exception as e:
            print(f"   [FLUX KO] {src.get('name', '?')} : {type(e).__name__}")
            continue
        for it in lot:
            if it.get("url") in vus_url:
                continue
            vus_url.add(it.get("url"))
            it["_source"] = src.get("name", "?")
            items.append(it)
    print(f"[COLLECTE] {len(items)} items depuis {len({i['_source'] for i in items})} sources\n")
    return items


def clusteriser(items: list[dict], seuil: float) -> list[list[dict]]:
    """Regroupement par similarité de titre pondérée IDF, lien simple.

    L'IDF est calculée SUR LA COLLECTE DU JOUR : un mot présent dans 40 titres
    (« France », « canicule » un jour de canicule) ne rapproche presque rien,
    un mot présent dans 3 titres rapproche beaucoup. C'est ce qui évite les
    faux positifs du filtre anti-doublon actuel, qui traite tous les mots de
    la même façon — « remplace » y pesait autant qu'un nom propre rare.
    """
    toks = [norm_tokens(i["title"]) for i in items]
    df = Counter()
    for s in toks:
        df.update(s)
    n = max(1, len(items))
    idf = {m: math.log(n / c) for m, c in df.items()}

    poids = [sum(idf.get(m, 0.0) for m in s) for s in toks]
    parent = list(range(len(items)))

    def trouver(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(items)):
        if not toks[a]:
            continue
        for b in range(a + 1, len(items)):
            if not toks[b]:
                continue
            communs = toks[a] & toks[b]
            if len(communs) < 2:
                continue  # jamais sur un seul mot — leçon du filtre anti-doublon
            num = sum(idf.get(m, 0.0) for m in communs)
            den = math.sqrt(poids[a] * poids[b]) or 1.0
            if num / den >= seuil:
                ra, rb = trouver(a), trouver(b)
                if ra != rb:
                    parent[ra] = rb

    groupes = defaultdict(list)
    for i in range(len(items)):
        groupes[trouver(i)].append(items[i])
    return sorted(groupes.values(), key=len, reverse=True)


def selection_actuelle(items: list[dict]) -> list[dict]:
    """Ce que le pipeline retiendrait aujourd'hui, mêmes fonctions, même ordre."""
    published_topics = {a.get("titre", "") for a in P.load_index()[:140]}
    candidats = []
    for src_nom in {i["_source"] for i in items}:
        lot = [i for i in items if i["_source"] == src_nom]
        candidats += P.filtrer_et_classer(lot, src_nom, published_topics, seuil_score=20)
    # Le pipeline trie GLOBALEMENT par score avant de sélectionner
    # (pipeline.py, `tous_candidats.sort(...)`). Omettre ce tri fait
    # mesurer un ordre qui n'existe pas — erreur commise le 11/08 sur
    # toutes les mesures de sélection de la session.
    candidats.sort(key=lambda c: c['_score'], reverse=True)
    return P.selectionner_meilleurs(candidats, nb_max=34)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seuils", action="store_true",
                    help="balayer plusieurs seuils au lieu d'un seul")
    ap.add_argument("--seuil", type=float, default=0.34)
    args = ap.parse_args()

    items = collecter()
    if not items:
        print("Aucun item collecté — flux injoignables depuis cette machine ?")
        return 1

    if args.seuils:
        print("Sensibilité au seuil (nb de grappes par taille) :")
        print(f"  {'seuil':>6}  {'≥2 médias':>10}  {'≥3':>5}  {'≥5':>5}  {'plus grande':>12}")
        for s in (0.22, 0.28, 0.34, 0.40, 0.48):
            gr = clusteriser(items, s)
            tailles = [len({x['_source'] for x in g}) for g in gr]
            print(f"  {s:>6.2f}  {sum(1 for t in tailles if t >= 2):>10}"
                  f"  {sum(1 for t in tailles if t >= 3):>5}"
                  f"  {sum(1 for t in tailles if t >= 5):>5}"
                  f"  {max(tailles):>12}")
        return 0

    grappes = clusteriser(items, args.seuil)
    grappes_multi = [g for g in grappes if len({x["_source"] for x in g}) >= 3]

    print(f"=== B. GRAPPES D'ÉVÉNEMENTS (seuil {args.seuil}) ===")
    print(f"{len(grappes_multi)} grappe(s) couverte(s) par ≥3 médias distincts\n")
    for g in grappes_multi[:12]:
        medias = sorted({x["_source"] for x in g})
        print(f"  [{len(medias)} médias] {g[0]['title'][:82]}")
        print(f"      {', '.join(medias[:8])}")

    sel = selection_actuelle(items)
    print(f"\n=== A. SÉLECTION ACTUELLE DU PIPELINE ===")
    print(f"{len(sel)} sujets retenus\n")
    for s in sel[:12]:
        print(f"  [score {s.get('_score', '?'):>4}] {s['title'][:82]}")

    # Recoupement : les grappes sont-elles dans la sélection, et inversement ?
    titres_sel = {P._titre_norme(s["title"]) for s in sel}
    dans_sel = sum(1 for g in grappes_multi
                   if any(P._titre_norme(x["title"]) in titres_sel for x in g))
    tokens_grappes = [set().union(*[norm_tokens(x["title"]) for x in g]) for g in grappes_multi]
    sel_isoles = 0
    for s in sel:
        ts = norm_tokens(s["title"])
        if not any(len(ts & tg) >= 2 for tg in tokens_grappes):
            sel_isoles += 1

    print(f"\n=== RECOUPEMENT ===")
    print(f"  grappes ≥3 médias présentes dans la sélection : {dans_sel}/{len(grappes_multi)}")
    print(f"  sujets sélectionnés couverts par UN SEUL média : {sel_isoles}/{len(sel)}")
    print()
    print("  Lecture : si la première ligne est basse, le barème rate des faits")
    print("  largement couverts. Si la seconde est haute, il sélectionne des")
    print("  sujets que personne d'autre ne juge dignes d'être traités.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
