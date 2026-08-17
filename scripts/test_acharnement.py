"""Ne pas repayer la génération d'un sujet déjà condamné deux fois.

Mesuré le 17/08 sur `verification_log.json` : 11 sujets totalisent 42
générations complètes, dont 31 sont des reprises d'un sujet déjà rejeté sur
`angle_insuffisant` — ~1,1 M tokens, un quota journalier entier, dépensé à
re-condamner. « nouvelles addictions » 11 fois, Edgar Morin 7 fois en 5 jours.

Le seuil est mesuré : les deux retours gagnants connus ont demandé 1 et 3
rejets préalables. Bloquer dès la 2e tentative les tuerait tous les deux ;
bloquer à partir de la 3e économise 20 générations et n'en coûte qu'un.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

echecs = []


def verifie(nom, cond, detail=""):
    print(f"  {'OK  ' if cond else 'ÉCHEC'} {nom} {detail}")
    if not cond:
        echecs.append(nom)


def _journal(entrees):
    """Écrit un journal temporaire et fait pointer le lecteur dessus."""
    d = tempfile.mkdtemp()
    p = Path(d) / "verification_log.json"
    p.write_text(json.dumps(entrees), encoding="utf-8")
    return d


def _avec_journal(entrees, fn):
    d = _journal(entrees)
    cwd = os.getcwd()
    os.chdir(d)
    try:
        os.makedirs("data", exist_ok=True)
        os.replace("verification_log.json", "data/verification_log.json")
        return fn()
    finally:
        os.chdir(cwd)


def _rejet(titre, jours_avant=0):
    return {
        "slug": "peu-importe",
        "statut": "rejete_qualite",
        "angle_insuffisant": True,
        "titre_rss": titre,
        "date": (datetime.now() - timedelta(days=jours_avant)).isoformat(),
    }


print("1. Le seuil mesuré : 2 rejets condamnent, 1 seul non")
condamnes = _avec_journal(
    [_rejet("Edgar Morin, penseur de la complexité, est mort"),
     _rejet("Edgar Morin, penseur de la complexité, est mort"),
     _rejet("Anomalie immunitaire et infections virales")],
    P._sujets_condamnes)
verifie("le sujet rejeté 2 fois est condamné",
        P._titre_norme("Edgar Morin, penseur de la complexité, est mort") in condamnes)
verifie("le sujet rejeté 1 fois ne l'est PAS — la 1re reprise est souvent gagnante",
        P._titre_norme("Anomalie immunitaire et infections virales") not in condamnes)

print("\n2. La fenêtre laisse revenir un sujet avec un angle neuf")
condamnes = _avec_journal(
    [_rejet("Canicule en France", jours_avant=30),
     _rejet("Canicule en France", jours_avant=30)],
    P._sujets_condamnes)
verifie("un sujet condamné il y a un mois est de nouveau tentable",
        P._titre_norme("Canicule en France") not in condamnes)

print("\n3. Seul `angle_insuffisant` condamne, pas les pannes techniques")
# Deux des neuf rejets du 01/08 étaient un quota épuisé et un JSON tronqué,
# journalisés sous le même statut que les décisions éditoriales. Une panne ne
# doit jamais condamner un sujet.
condamnes = _avec_journal(
    [{"slug": "x", "statut": "rejete_qualite", "titre_rss": "Quota épuisé",
      "date": datetime.now().isoformat()},
     {"slug": "x", "statut": "rejete_qualite", "titre_rss": "Quota épuisé",
      "date": datetime.now().isoformat()}],
    P._sujets_condamnes)
verifie("un rejet sans `angle_insuffisant` ne compte pas",
        P._titre_norme("Quota épuisé") not in condamnes)

print("\n4. Aucun appariement approximatif — égalité exacte seulement")
# Le rapprochement flou de titres a échoué trois fois (26/07, 28/07, 02/08).
# Un blocage ici est permanent sur la fenêtre : on n'accepte que la certitude.
condamnes = _avec_journal(
    [_rejet("Éclipse solaire du 12 août 2026"),
     _rejet("Éclipse solaire du 12 août 2026")],
    P._sujets_condamnes)
verifie("le titre exact est condamné",
        P._titre_norme("Éclipse solaire du 12 août 2026") in condamnes)
verifie("un titre voisin ne l'est pas",
        P._titre_norme("Éclipse solaire visible en France") not in condamnes)

print("\n5. Journal absent ou illisible → aucun blocage")
d = tempfile.mkdtemp()
cwd = os.getcwd()
os.chdir(d)
try:
    verifie("journal absent", P._sujets_condamnes() == set())
    os.makedirs("data", exist_ok=True)
    Path("data/verification_log.json").write_text("{pas du json", encoding="utf-8")
    verifie("journal illisible", P._sujets_condamnes() == set())
finally:
    os.chdir(cwd)

print("\n6. La sélection écarte réellement le sujet condamné")
candidats = [
    {"title": "Edgar Morin, penseur de la complexité, est mort", "_score": 999,
     "_cat": "societe", "id": "a"},
    {"title": "Le Sénat adopte le budget rectificatif", "_score": 10,
     "_cat": "societe", "id": "b"},
]
vrai = P._sujets_condamnes
P._sujets_condamnes = lambda *a, **k: {
    P._titre_norme("Edgar Morin, penseur de la complexité, est mort")}
try:
    sel = P.selectionner_meilleurs(candidats, nb_max=5)
finally:
    P._sujets_condamnes = vrai
titres = [s["title"] for s in sel]
verifie("le sujet condamné est écarté malgré le meilleur score",
        "Edgar Morin, penseur de la complexité, est mort" not in titres)
verifie("les autres sujets passent normalement",
        "Le Sénat adopte le budget rectificatif" in titres)

print()
sys.exit(1 if echecs else 0)
