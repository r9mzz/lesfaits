# -*- coding: utf-8 -*-
"""Non-régression : détection des mineurs, et ouverture des épidémies (11/08).

Deux règles verrouillées ici.

1. `_MINEUR_RE` — la protection la plus sensible du pipeline. Sa version
   d'avant le 11/08 laissait passer « un collégien blessé », « une lycéenne
   victime de harcèlement », « un adolescent de 16 ans tué dans une rixe » :
   le motif finissait par des radicaux tronqués suivis de `\\b`, et « bless »
   suivi de « é » ne crée aucune frontière de mot. Ne JAMAIS réintroduire
   `radical\\b` — écrire `radical\\w*`. Même piège trouvé le même jour dans le
   filtre commercial (« 400 € ») et dans la détection de procédure pénale
   (« condamné à 18 mois »).

2. L'ouverture de la couche 3 aux épidémies : une épidémie en cours ne doit
   plus être rejetée par `_est_rejete_sensible_deterministe`, mais reste
   soumise à l'exigence de source officielle de
   `sujet_sante_sans_source_officielle`. Le volet pénal garde son veto.

    python scripts/test_mineur_et_sensible.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402

ok = True

DOIT_DETECTER = [
    "Un collégien blessé lors d'une agression devant son établissement",
    "Un collégien a été blessé hier",
    "Une lycéenne victime de harcèlement",
    "Un élève blessé dans la cour",
    "Un adolescent mis en cause dans une affaire",
    "Un mineur impliqué dans l'accident",
    "Une mineure entendue par les enquêteurs",
    "Un enfant victime d'un accident domestique",
    "Un enfant blessé par un chien",
    "Un adolescent de 16 ans tué dans une rixe à Montpellier",
    "Deux adolescents de 14 ans blessés dans la collision",
    "Des collégiens agressés à la sortie des cours",
]
# « mineur de fond » reste un faux positif connu et ASSUMÉ : sur un sujet
# aussi sensible, une fausse alerte coûte un article, une omission coûte la
# publication automatique d'un article impliquant un enfant.
NE_DOIT_PAS = [
    "Les collégiens rentrent le 1er septembre",
    "Le lycée Voltaire ouvre une filière numérique",
    "Un élève de Polytechnique remporte le concours",
    "La réforme du collège adoptée par le Sénat",
    "Les enfants passent trois heures par jour devant un écran",
]

print("=== 1. MINEURS — doivent déclencher ===")
for t in DOIT_DETECTER:
    m = P._MINEUR_RE.search(t)
    if not m:
        ok = False
    print(f"  {'OK   ' if m else 'ÉCHEC'}  {t[:66]}")

print("\n=== 1. MINEURS — ne doivent pas déclencher ===")
for t in NE_DOIT_PAS:
    m = P._MINEUR_RE.search(t)
    if m:
        ok = False
    print(f"  {'OK   ' if not m else 'FAUX+'}  {t[:66]}")


def _art(titre, faits, sources):
    return {"titre": titre, "resume": [titre],
            "corps": {"faits": faits, "contexte": "", "nuances": ""},
            "sources": [{"institution": n, "url": u} for n, u in sources]}


OFFICIELLE = [("OMS", "https://www.who.int/x"), ("Le Monde", "https://www.lemonde.fr/a")]
PRESSE = [("Le Monde", "https://www.lemonde.fr/a"), ("RFI", "https://www.rfi.fr/b")]

# (libellé, article, rejet_couche3_attendu, modération_santé_attendue)
CAS_COUCHE3 = [
    ("épidémie + source officielle → passe au fact-check",
     _art("Ebola : l'épidémie a fait 2 000 morts en RDC",
          "L'épidémie est en cours selon l'OMS.", OFFICIELLE), False, False),
    ("épidémie SANS source officielle → modération",
     _art("Ebola : l'épidémie a fait 2 000 morts en RDC",
          "L'épidémie est en cours.", PRESSE), False, True),
    ("terrorisme + enquête en cours → rejet maintenu",
     _art("Attentat déjoué : enquête en cours",
          "L'enquête judiciaire est en cours.", PRESSE), True, False),
    ("mineur → rejet maintenu",
     _art("Un collégien blessé lors d'une agression",
          "Un collégien blessé devant son établissement.", PRESSE), True, False),
]

print("\n=== 2. COUCHE 3 — épidémies ouvertes, pénal et mineurs fermés ===")
for label, art, rejet_attendu, moderation_attendue in CAS_COUCHE3:
    rejet, motif = P._est_rejete_sensible_deterministe(art)
    moderation = P.sujet_sante_sans_source_officielle(art)
    conforme = (rejet == rejet_attendu) and (moderation == moderation_attendue)
    if not conforme:
        ok = False
    print(f"  {'OK   ' if conforme else 'ÉCHEC'}  {label}")
    if rejet:
        print(f"           motif : {motif}")

print("\n" + ("TOUS CONFORMES" if ok else "RÉGRESSION"))
sys.exit(0 if ok else 1)
