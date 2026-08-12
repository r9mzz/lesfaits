# -*- coding: utf-8 -*-
"""Non-régression du juge de pertinence documentaire (12/08).

Le juge annote chaque source d'un `_pertinence` pour que les documents
traitant le sujet précis passent devant les pages permanentes. Ce qui est
vérifié ici, ce n'est PAS sa justesse — elle a été mesurée par backtest sur
un vrai modèle (`scripts/test_juge_sources.py`, 60 paires) — mais son
innocuité : il ne doit jamais faire perdre un article.

Aucun appel réseau, aucun token : le client Groq est simulé.

    python scripts/test_pertinence_sources.py
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("GROQ_API_KEY", "cle-de-test")
import pipeline as P  # noqa: E402

echecs: list[str] = []


def verifie(libelle: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  OK   {libelle}")
    else:
        print(f"  ÉCHEC {libelle} {detail}")
        echecs.append(libelle)


class ClientSimule:
    """Rend le verdict programmé, ou lève si `panne` est vrai."""

    def __init__(self, verdicts, panne=False):
        self.verdicts, self.panne, self.appels = list(verdicts), panne, 0
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        self.appels += 1
        if self.panne:
            raise RuntimeError("rate limit simulé")
        mot = self.verdicts.pop(0) if self.verdicts else "PERTINENTE"
        msg = type("M", (), {"content": mot})()
        return type("R", (), {"choices": [type("Ch", (), {"message": msg})()]})()


def poser(verdicts, panne=False):
    simule = ClientSimule(verdicts, panne)
    P.Groq = lambda **kw: simule
    return simule


_GROQ_ORIG = P.Groq
SOURCES = [
    {"institution": "WHO", "titre": "Rougeole", "url": "https://who.int/fact-sheets/measles"},
    {"institution": "Sciences et Avenir", "titre": "Un antiviral à l'étude",
     "url": "https://sciencesetavenir.fr/sante/un-antiviral-rougeole"},
    {"institution": "Inserm", "titre": "Rougeole", "url": "https://inserm.fr/dossier/rougeole"},
]
TITRE = "Rougeole : un antiviral à l'étude contre la recrudescence"

print("\n1. Annotation et classement")
srcs = [dict(s) for s in SOURCES]
poser(["GENERALE", "PERTINENTE", "GENERALE"])
ok = P.juger_pertinence_sources(TITRE, srcs)
verifie("le juge rend un verdict", ok)
verifie("la source du sujet est marquée pertinente",
        srcs[1].get("_pertinence") == "pertinente", f"(obtenu : {srcs[1].get('_pertinence')})")
verifie("les pages permanentes sont marquées générales",
        srcs[0].get("_pertinence") == "generale" and srcs[2].get("_pertinence") == "generale")

rang = {"pertinente": 0, "generale": 1, "": 1, "hors_sujet": 2}
classe = sorted(srcs, key=lambda s: rang.get(s.get("_pertinence", ""), 1))
verifie("après tri, la source pertinente passe en tête",
        classe[0]["institution"] == "Sciences et Avenir")

print("\n2. Innocuité — un juge en panne ne doit jamais coûter un article")
srcs = [dict(s) for s in SOURCES]
poser([], panne=True)
verifie("une panne API ne lève pas d'exception",
        P.juger_pertinence_sources(TITRE, srcs) is False)
verifie("aucune source n'est annotée après une panne",
        all("_pertinence" not in s for s in srcs))
verifie("aucune source n'est supprimée après une panne", len(srcs) == 3)

# Une erreur interrompt la boucle : en rate limit, insister sur dix sources
# ferait attendre le run entier pour un simple tri.
simule = poser([], panne=True)
P.juger_pertinence_sources(TITRE, [dict(s) for s in SOURCES])
verifie("le juge renonce dès la première erreur", simule.appels == 1,
        f"(appels : {simule.appels})")

print("\n3. Garde-fous d'appel")
srcs = [dict(s) for s in SOURCES]
os.environ["JUGE_SOURCES"] = "0"
simule = poser(["PERTINENTE"])
verifie("l'interrupteur JUGE_SOURCES=0 coupe tout appel",
        P.juger_pertinence_sources(TITRE, srcs) is False and simule.appels == 0)
os.environ["JUGE_SOURCES"] = "1"

simule = poser(["PERTINENTE"])
verifie("un titre vide n'appelle pas le modèle",
        P.juger_pertinence_sources("", srcs) is False and simule.appels == 0)

# Réponse inattendue : ne pas classer au hasard vaut mieux que classer faux.
srcs = [dict(SOURCES[0])]
poser(["PEUT-ÊTRE"])
P.juger_pertinence_sources(TITRE, srcs)
verifie("une réponse inattendue ne produit aucune annotation",
        "_pertinence" not in srcs[0], f"(obtenu : {srcs[0].get('_pertinence')})")

# Le plafond borne le coût : les 45 résultats bruts ne partent pas tous dans
# le prompt, juger la queue serait payer pour classer ce qui ne sera pas lu.
beaucoup = [dict(SOURCES[0]) for _ in range(30)]
simule = poser(["GENERALE"] * 30)
P.juger_pertinence_sources(TITRE, beaucoup)
verifie(f"le plafond limite à {P.JUGE_SOURCES_MAX} appels",
        simule.appels == P.JUGE_SOURCES_MAX, f"(appels : {simule.appels})")

P.Groq = _GROQ_ORIG
print()
if echecs:
    print(f"ÉCHEC — {len(echecs)} test(s) : {', '.join(echecs)}")
    sys.exit(1)
print("Tous les tests passent.")
