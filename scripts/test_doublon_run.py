# -*- coding: utf-8 -*-
"""Un seul sujet par événement dans un même run (14/08).

Constat en rejouant la sélection sur les 863 dépêches du jour : la censure par
le Conseil constitutionnel de l'interdiction des réseaux sociaux aux moins de
15 ans occupait SIX des onze premières places, sous six titres différents. Sur
un run à six tentatives, c'était le run entier consacré à un seul fait — et six
articles quasi identiques publiés dans la même heure.

Le filtre anti-doublon historique ne pouvait pas les voir : il compare les MOTS
DES TITRES, et six rédactions couvrant la même décision écrivent six titres
sans mot distinctif commun (« Les Sages ont censuré », « l'interdiction
s'effondre »…). La veille, elle, les avait déjà regroupés.

    python scripts/test_doublon_run.py
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("GROQ_API_KEY", "x")
import pipeline as P  # noqa: E402

echecs: list[str] = []


def verifie(libelle, condition, detail=""):
    print(("  OK   " if condition else "  ÉCHEC ") + libelle + ("" if condition else f" {detail}"))
    if not condition:
        echecs.append(libelle)


def cand(titre, grappe=None, cat="societe"):
    it = {"title": titre, "url": f"https://x.fr/{abs(hash(titre))}", "content": titre,
          "source_name": "X", "_cat": cat, "_score": 90}
    if grappe:
        it["_veille"] = {"grappe": grappe, "heures_visible": 0, "age_h": 1,
                         "n_flux_grappe": 5, "passages": 2}
    return it


print("\nUn seul sujet par événement")
TITRES = [
    "L'interdiction des réseaux sociaux aux moins de 15 ans censurée par le Conseil",
    "Pourquoi les Sages ont censuré l'interdiction des réseaux sociaux",
    "France : le Conseil constitutionnel censure l'interdiction",
    "L'interdiction des réseaux sociaux aux moins de 15 ans s'effondre",
]
sel = P.selectionner_meilleurs([cand(t, "evt-cc") for t in TITRES], nb_max=6)
verifie("quatre dépêches du même événement → une seule retenue", len(sel) == 1,
        f"(retenus : {len(sel)})")

# Des événements DIFFÉRENTS ne doivent jamais être fusionnés.
divers = [cand("Le Conseil constitutionnel censure une loi", "evt-cc"),
          cand("Séisme en Colombie : 240 morts", "evt-seisme", "science"),
          cand("Ebola : 2 000 morts en RDC", "evt-ebola", "sante")]
verifie("trois événements distincts → trois retenus",
        len(P.selectionner_meilleurs(divers, nb_max=6)) == 3)

# Un candidat que la veille n'a pas vu ne doit jamais être écarté à ce titre :
# le bonus comme le dédoublonnage ne peuvent qu'AJOUTER de l'information.
# ⚠ 20/08 — ces trois titres étaient « Sujet A / B / C jamais vu par la
# veille ». Ils partageaient donc « jamais » et « veille », et le filtre de
# DIVERSITÉ ajouté ce jour les a écartés — non pas à cause de la veille, mais
# parce qu'ils se ressemblaient littéralement. La fixture mesurait un artefact
# d'elle-même. Trois sujets réellement distincts, comme le seraient de vrais
# candidats, rendent au test ce qu'il prétend vérifier : l'absence de signal de
# veille n'écarte personne.
inconnus = [cand("Le Honduras place 80 % de son territoire en alerte"),
            cand("Apple ouvre son App Store aux règles européennes"),
            cand("Un trou noir géant conforte la théorie d'Einstein")]
verifie("sans signal de veille, aucun candidat n'est écarté",
        len(P.selectionner_meilleurs(inconnus, nb_max=6)) == 3)

# La première dépêche de l'événement est celle qui reste.
sel = P.selectionner_meilleurs([cand(t, "evt-cc") for t in TITRES], nb_max=6)
verifie("c'est la première du classement qui est gardée",
        sel[0]["title"] == TITRES[0], f"(gardé : {sel[0]['title'][:40]})")

print()
sys.exit(1 if echecs else 0)
