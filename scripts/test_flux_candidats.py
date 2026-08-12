# -*- coding: utf-8 -*-
"""Teste des flux RSS candidats AVANT de les ajouter au pipeline.

`CLAUDE.md` documente la règle : ne jamais ajouter un flux sans mesurer son
rendement réel. La vague d'ajouts du 19/07 comportait 13 flux morts sur 14.

Ce script utilise le PARSEUR DU PIPELINE (`fetch_rss`), donc il reproduit
exactement ce que verrait un run — y compris la gestion des flux Atom, réparée
le 28/07.

⚠ Un flux qui répond ici peut échouer depuis GitHub Actions : les WAF de
`.gouv.fr`, Les Échos ou 20 Minutes renvoient 403 à l'IP des runners. Ce test
écarte les URL fausses ou vides ; il ne remplace pas `check_feeds.py`, qui doit
valider depuis le runner avant adoption définitive.

    python scripts/test_flux_candidats.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402

# Institutions qui PUBLIENT elles-mêmes — exactement les sources primaires qui
# manquent à 69 % des articles publiés, et que `SOURCES_MAJEURES` valorise déjà
# (+35) sans qu'elles soient jamais collectées.
CANDIDATS = [
    {"name": "INSEE",                 "url": "https://www.insee.fr/fr/information/rss"},
    {"name": "INSEE Publications",    "url": "https://www.insee.fr/fr/statistiques/rss"},
    {"name": "Cour des comptes",      "url": "https://www.ccomptes.fr/fr/rss.xml"},
    {"name": "Vie publique",          "url": "https://www.vie-publique.fr/rss.xml"},
    {"name": "CNIL",                  "url": "https://www.cnil.fr/fr/rss.xml"},
    {"name": "ANSES",                 "url": "https://www.anses.fr/fr/flux-actualites.rss"},
    {"name": "Banque de France",      "url": "https://www.banque-france.fr/rss.xml"},
    {"name": "ADEME",                 "url": "https://presse.ademe.fr/feed"},
    {"name": "Météo-France",          "url": "https://meteofrance.fr/rss/actualites"},
    {"name": "Assemblée nationale",   "url": "https://www2.assemblee-nationale.fr/feeds/detail/actualites"},
    {"name": "Commission européenne", "url": "https://ec.europa.eu/commission/presscorner/api/rss?language=fr&pagesize=30"},
    {"name": "Parlement européen",    "url": "https://www.europarl.europa.eu/rss/doc/press-releases/fr.xml"},
    {"name": "OMS actualités",        "url": "https://www.who.int/rss-feeds/news-english.xml"},
    {"name": "INRAE",                 "url": "https://www.inrae.fr/actualites/rss.xml"},
    {"name": "CEA",                   "url": "https://www.cea.fr/Pages/RSS.aspx"},
    {"name": "IGN",                   "url": "https://www.ign.fr/institut/rss.xml"},
    {"name": "Défenseur des droits",  "url": "https://www.defenseurdesdroits.fr/rss.xml"},
    {"name": "Autorité concurrence",  "url": "https://www.autoritedelaconcurrence.fr/fr/rss.xml"},
    {"name": "France Stratégie",      "url": "https://www.strategie.gouv.fr/rss.xml"},
    {"name": "Institut Pasteur",      "url": "https://www.pasteur.fr/fr/rss.xml"},
]


def main() -> int:
    ok, vides, morts = [], [], []
    print(f"Test de {len(CANDIDATS)} flux candidats avec le parseur du pipeline…\n")
    for src in CANDIDATS:
        try:
            items = P.fetch_rss(src)
        except Exception as exc:
            morts.append((src, type(exc).__name__))
            print(f"  ✗ MORT   {src['name']:<24} {type(exc).__name__}")
            continue
        if not items:
            vides.append(src)
            print(f"  ~ VIDE   {src['name']:<24} (répond, 0 article)")
            continue
        ok.append((src, items))
        exemple = items[0].get("title", "")[:52]
        print(f"  ✓ OK     {src['name']:<24} {len(items):>3} items · « {exemple} »")

    print(f"\n=== BILAN ===")
    print(f"  exploitables : {len(ok)}")
    print(f"  vides        : {len(vides)}")
    print(f"  injoignables : {len(morts)}")
    if ok:
        print(f"\nÀ ajouter à RSS_SOURCES (après validation par check_feeds.py "
              f"depuis le runner) :")
        for src, items in ok:
            print(f'    {{"name": "{src["name"]}", "url": "{src["url"]}"}},')
    return 0


if __name__ == "__main__":
    sys.exit(main())
