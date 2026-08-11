# -*- coding: utf-8 -*-
"""MESURE — combien de candidats survivent AVANT génération ?

Question posée le 11/08 : sur les ~34 sujets que la sélection retient, combien
sont réellement publiables selon la charte, avant même qu'un token soit dépensé ?

Le run du 11/08 a tenté 6 sujets et n'en a publié aucun : deux bons plans
commerciaux (le filtre € était inerte, corrigé depuis), deux sujets sensibles
rejetés à raison, un essai sans actualité. Si la proportion se confirme sur
toute la sélection, le problème n'est ni le quota ni le format — c'est que la
sélection livre majoritairement des sujets que la charte interdit de publier.

Ce script rejoue, sur la sélection réelle, les portes DÉTERMINISTES qui
s'appliquent avant génération. Il ne peut pas simuler le jugement LLM
(`sujet_sensible`, `angle_insuffisant`) : ceux-là sont signalés à part comme
risque estimé, jamais comptés comme rejets certains.

    python scripts/mesure_survie_candidats.py            # réutilise le cache
    python scripts/mesure_survie_candidats.py --recolter

Aucun token Groq, aucun appel DuckDuckGo.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402
from mesure_clustering import collecter  # noqa: E402
from run_pipeline import SENSITIVE_PREFILTER_TERMS  # noqa: E402

CACHE = Path(__file__).parent.parent / "data" / "cache_collecte_mesure.json"


def _sans_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def corpus(recolter: bool) -> list[dict]:
    if CACHE.exists() and not recolter:
        items = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"[CACHE] {len(items)} items relus\n")
        return items
    items = collecter()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recolter", action="store_true")
    args = ap.parse_args()

    items = corpus(args.recolter)
    published_topics = {a.get("titre", "") for a in P.load_index()[:140]}

    candidats = []
    for nom in {i["_source"] for i in items}:
        lot = [dict(i) for i in items if i["_source"] == nom]
        candidats += P.filtrer_et_classer(lot, nom, published_topics, seuil_score=20)
    selection = P.selectionner_meilleurs(candidats, nb_max=34)
    print(f"sélection réelle : {len(selection)} sujets sur {len(items)} collectés\n")

    survivants, morts = [], []
    for s in selection:
        titre = s.get("title", "")
        contenu = s.get("content", "")
        plein = f"{titre} {contenu}"
        motifs = []

        if P.classifier_type_article(titre, contenu) == "rejete":
            motifs.append("listicle / lifestyle / portrait polémique")
        if P._COMMERCE_RE.search(plein[:800]):
            motifs.append("contenu commercial")
        if P._PR_MARQUE_RE.search(plein[:800]):
            motifs.append("communication de marque")
        norm = _sans_accents(plein)
        touches = [t.strip() for t in SENSITIVE_PREFILTER_TERMS
                   if _sans_accents(t).strip() in norm]
        if touches:
            motifs.append(f"préfiltre judiciaire ({touches[0]})")

        (morts if motifs else survivants).append((s, motifs))

    print(f"=== PORTES DÉTERMINISTES (avant toute génération) ===")
    print(f"  écartés  : {len(morts):2} / {len(selection)}")
    print(f"  survivent: {len(survivants):2} / {len(selection)}\n")
    for s, m in morts[:14]:
        print(f"   ✗ {s['title'][:66]}")
        print(f"       {' + '.join(m)}")

    # Risque LLM estimé : vocabulaire que la vérification rejette en aval.
    # NE PAS compter comme rejet — c'est une estimation, pas une mesure.
    VOCAB_SENSIBLE = ("mort", "morts", "tue", "tuee", "victime", "victimes",
                      "blesse", "blesses", "seisme", "attaque", "guerre",
                      "condamne", "proces", "epidemie", "incendie criminel")
    a_risque = [s for s, _ in survivants
                if any(v in _sans_accents(s.get("title", "")) for v in VOCAB_SENSIBLE)]
    print(f"\n=== RISQUE ESTIMÉ, NON MESURÉ ===")
    print(f"  survivants dont le TITRE porte du vocabulaire que la")
    print(f"  vérification rejette souvent (mort, victime, procès, épidémie…) :")
    print(f"     {len(a_risque)} / {len(survivants)}")
    for s in a_risque[:8]:
        print(f"       ~ {s.get('title','')[:64]}")
    print()
    print(f"  → plancher réaliste de sujets publiables : "
          f"{len(survivants) - len(a_risque)} à {len(survivants)} sur {len(selection)}")
    print("  Le pipeline en tente 6 par run (RÉSERVE). La question n'est donc")
    print("  pas « en a-t-on assez ? » mais « les 6 tentés sont-ils les bons ? ».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
