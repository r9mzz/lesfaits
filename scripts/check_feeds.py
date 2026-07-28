#!/usr/bin/env python3
"""Diagnostic des flux RSS/Atom — à lancer depuis GitHub Actions.

Mesure le RENDEMENT RÉEL de chaque source, pas seulement l'absence d'erreur :
un flux Atom lu comme du RSS renvoyait 0 article sans lever la moindre erreur
et paraissait fonctionner dans les logs (cas The Conversation France, constat
28/07). Teste aussi une liste d'URLs candidates pour remplacer les flux morts,
afin de ne jamais rebrancher une source sur une URL devinée.

    python scripts/check_feeds.py            # sources actuelles
    python scripts/check_feeds.py --candidats # + URLs de remplacement testées
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline as p  # noqa: E402

# URLs candidates pour les sources actuellement mortes. Plusieurs pistes par
# source : on garde celle qui répond ET renvoie des articles.
CANDIDATS = {
    "Novethic": [
        "https://www.novethic.fr/feed",
        "https://www.novethic.fr/rss.xml",
        "https://www.novethic.fr/rss/toute-l-actualite.xml",
    ],
    "Légifrance JORF": [
        "https://www.legifrance.gouv.fr/contenu/rss/jorf",
        "https://www.legifrance.gouv.fr/rss/jorf.xml",
    ],
    "INSEE": [
        "https://www.insee.fr/fr/information/rss",
        "https://www.insee.fr/fr/statistiques/rss",
        "https://www.insee.fr/fr/rss",
    ],
    "Les Échos": [
        "https://services.lesechos.fr/rss/les-echos-economie.xml",
        "https://services.lesechos.fr/rss/la-une.xml",
        "https://www.lesechos.fr/rss/rss_une.xml",
    ],
    "Le Parisien": [
        "https://feeds.leparisien.fr/leparisien/rss",
        "https://feeds.leparisien.fr/leparisien/rss/une",
        "https://www.leparisien.fr/arc/outboundfeeds/rss/?outputType=xml",
    ],
    "L'Express": [
        "https://www.lexpress.fr/rss/alaune.xml",
        "https://www.lexpress.fr/rss.xml",
        "https://www.lexpress.fr/arc/outboundfeeds/rss/?outputType=xml",
    ],
    "20 Minutes": [
        "https://www.20minutes.fr/feeds/rss-une.xml",
        "https://www.20minutes.fr/rss/actu-france.xml",
        "https://www.20minutes.fr/rss/une.xml",
    ],
    "CEA": [
        "https://www.cea.fr/rss/actualites.xml",
        "https://www.cea.fr/presse/rss",
        "https://www.cea.fr/rss",
    ],
    "INRAE": [
        "https://www.inrae.fr/actualites/rss",
        "https://www.inrae.fr/rss/actualites",
        "https://www.inrae.fr/rss.xml",
    ],
    "Cour des comptes": [
        "https://www.ccomptes.fr/fr/rss/publications.xml",
        "https://www.ccomptes.fr/fr/rss.xml",
    ],
    "Sénat": [
        "https://www.senat.fr/themes/rss/therss4.rss",
        "https://www.senat.fr/themes/rss/therss2.rss",
        "https://www.senat.fr/rss/actualites.xml",
    ],
    "Assemblée nationale": [
        "https://www.assemblee-nationale.fr/dyn/rss/actualites.xml",
        "https://www.assemblee-nationale.fr/dyn/rss/rss_dossiers_legislatifs.xml",
    ],
    "Banque de France": [
        "https://www.banque-france.fr/fr/rss.xml",
        "https://www.banque-france.fr/rss.xml",
    ],
    # Sources supplémentaires envisagées pour élargir le gisement — testées
    # ici AVANT tout ajout à RSS_SOURCES.
    "[new] France Culture": ["https://radiofrance.fr/franceculture/rss"],
    "[new] Courrier international": ["https://www.courrierinternational.com/feed/all/rss.xml"],
    "[new] Slate.fr": ["https://www.slate.fr/rss.xml"],
    "[new] Le Monde Idées": ["https://www.lemonde.fr/idees/rss_full.xml"],
    "[new] Le Monde Décodeurs": ["https://www.lemonde.fr/les-decodeurs/rss_full.xml"],
    "[new] Le Monde International": ["https://www.lemonde.fr/international/rss_full.xml"],
    "[new] France Info Sciences": ["https://www.francetvinfo.fr/sciences.rss"],
    "[new] Ouest-France Sciences": ["https://www.ouest-france.fr/sciences/rss.xml"],
    "[new] INSERM presse": ["https://presse.inserm.fr/feed/"],
    "[new] IRD": ["https://www.ird.fr/rss.xml"],
    "[new] Ademe presse": ["https://presse.ademe.fr/feed"],
    "[new] Public Sénat": ["https://www.publicsenat.fr/rss.xml"],
}


def tester(nom: str, url: str) -> tuple[str, int]:
    """Retourne (statut, nb_items). Le nb d'items est le vrai signal."""
    try:
        items = p.fetch_rss({"name": nom, "url": url})
        return ("OK" if items else "VIDE (0 article, sans erreur)"), len(items)
    except Exception as e:
        return f"ERREUR {str(e)[:70]}", 0


def main():
    print("=" * 78)
    print("SOURCES ACTUELLEMENT CONFIGURÉES")
    print("=" * 78)
    morts, vides, ok = [], [], 0
    total_items = 0
    for src in p.RSS_SOURCES:
        statut, n = tester(src["name"], src["url"])
        total_items += n
        marque = "  " if statut == "OK" else "!!"
        print(f"{marque} {src['name']:32s} {n:3d} art.  {statut if statut != 'OK' else ''}")
        if statut.startswith("ERREUR"):
            morts.append(src["name"])
        elif n == 0:
            vides.append(src["name"])
        else:
            ok += 1
    print()
    print(f"BILAN : {ok}/{len(p.RSS_SOURCES)} sources produisent des articles "
          f"— {total_items} articles collectés au total")
    if morts:
        print(f"  MORTES ({len(morts)}) : {', '.join(morts)}")
    if vides:
        print(f"  SILENCIEUSES ({len(vides)}) : {', '.join(vides)}")

    if "--candidats" not in sys.argv:
        return
    print()
    print("=" * 78)
    print("URLS CANDIDATES (remplacements + nouvelles sources)")
    print("=" * 78)
    for nom, urls in CANDIDATS.items():
        print(f"\n{nom}")
        for url in urls:
            statut, n = tester(nom, url)
            marque = " ✓" if statut == "OK" else " ·"
            print(f"  {marque} {n:3d} art.  {url}")
            if statut != "OK":
                print(f"         → {statut}")


if __name__ == "__main__":
    main()
