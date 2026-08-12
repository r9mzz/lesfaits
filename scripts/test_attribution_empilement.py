# -*- coding: utf-8 -*-
"""Non-régression de la détection d'attribution et d'empilement (audit 12/08).

L'audit des 161 articles longs publiés a montré que `sources_non_fusionnees`
ne voyait que 16 % des empilements là où le comptage manuel des phrases
attribuées consécutives en trouve 40 %. Deux causes, toutes deux couvertes
ici, plus l'extension de `prise_de_position` faite dans la foulée.

Les textes sont ceux réellement publiés (principalement
articles/rougeole-antiviral-etude.html, cas d'école de l'audit). Aucun appel
réseau, aucun token : lançable à tout moment.

    python scripts/test_attribution_empilement.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
import pipeline as P  # noqa: E402

echecs: list[str] = []


def verifie(libelle: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  OK   {libelle}")
    else:
        print(f"  ÉCHEC {libelle} {detail}")
        echecs.append(libelle)


# ── 1. Le nom précédé d'un article doit être vu ──────────────────────────────
# Avant le 12/08 : « Selon le WHO » ne capturait rien, car le motif exigeait une
# majuscule juste après « Selon » et rencontrait « le ». La phrase comptait donc
# comme NON attribuée, ce qui cassait la série de phrases consécutives.
print("\n1. Nom de source précédé d'un article")
for phrase, attendu in [
    ("D’après le WHO, la rougeole est une maladie virale très contagieuse.", "WHO"),
    ("Selon le WHO, la proportion d’enfants vaccinés était de 84 % en 2024.", "WHO"),
    ("D’après le Pasteur, la recrudescence soulève plusieurs interrogations.", "Pasteur"),
    ("Selon l’Inserm, la vaccination a évité un nombre significatif de décès.", "Inserm"),
    ("Selon la Cour des comptes, le dispositif coûte 3 milliards d’euros.", "Cour des comptes"),
    ("Selon Santepubliquefrance, la France fait face à une recrudescence.", "Santepubliquefrance"),
]:
    noms = P._sources_attribuees(phrase)
    verifie(f"« {phrase[:42]}… » → {attendu}", attendu in noms, f"(obtenu : {sorted(noms)})")

# ── 2. Un nom à mot minuscule interne ne doit pas être tronqué ───────────────
# « D'après Santé publique France » ne rendait que « Santé ». Le même organisme
# apparaissait alors sous deux noms, gonflant le compte de sources DISTINCTES.
print("\n2. Nom de source contenant un mot en minuscule")
noms = P._sources_attribuees(
    "D’après Santé publique France, la rougeole est une infection très contagieuse.")
verifie("« Santé publique France » n'est pas tronqué à « Santé »",
        "Santé publique France" in noms, f"(obtenu : {sorted(noms)})")

# Une conjonction ne doit PAS être absorbée dans le nom, sans quoi deux sources
# distinctes fusionneraient en une seule (« Le Monde et Le »).
noms = P._sources_attribuees("Selon Le Monde et Le Figaro, le texte a été adopté.")
verifie("« Le Monde et Le Figaro » ne fusionne pas en un nom unique",
        not any("et" in n.split() for n in noms), f"(obtenu : {sorted(noms)})")

# ── 3. Deux orthographes du même organisme = UNE source ──────────────────────
print("\n3. Normalisation des noms de sources")
verifie("« Santepubliquefrance » ≡ « Santé publique France »",
        P.nom_source_normalise("Santepubliquefrance")
        == P.nom_source_normalise("Santé publique France"))
verifie("« Le Monde » ≢ « Le Figaro »",
        P.nom_source_normalise("Le Monde") != P.nom_source_normalise("Le Figaro"))

# ── 4. L'empilement du cas d'école est détecté ───────────────────────────────
# Section « Les faits » de rougeole-antiviral-etude, publiée le 04/08 : quatre
# phrases d'affilée attribuées, deux organismes seulement — donc de la
# non-fusion, pas de la corroboration.
print("\n4. Empilement « une phrase = une source »")
ROUGEOLE = {"corps": {"faits": (
    "D’après le WHO, la rougeole est une maladie virale très contagieuse qui peut "
    "entraîner des complications graves. Selon Santepubliquefrance, la France "
    "hexagonale fait face à une recrudescence des cas depuis le début de l’année 2025. "
    "Selon le WHO, la proportion d’enfants ayant reçu une première dose de vaccin "
    "antirougeoleux était de 84 % en 2024. D’après Santé publique France, la rougeole "
    "est une infection parmi les plus contagieuses, aux complications pouvant être graves."
), "contexte": "", "nuances": ""}}
verifie("4 phrases attribuées d'affilée → détecté", bool(P.sources_non_fusionnees(ROUGEOLE)))

# Le texte fusionné selon la règle 10 ne doit RIEN déclencher : sans cette
# moitié du test, on ne saurait pas si le détecteur sait dire non.
FUSIONNE = {"corps": {"faits": (
    "Selon l’OMS et Santé publique France, la rougeole est une infection parmi les plus "
    "contagieuses et la France fait face à une recrudescence des cas depuis 2025. "
    "La couverture vaccinale en première dose atteignait 84 % en 2024, contre les 95 % "
    "nécessaires pour interrompre la circulation du virus."
), "contexte": "", "nuances": ""}}
verifie("texte à attribution groupée → aucun signalement",
        not P.sources_non_fusionnees(FUSIONNE),
        f"(obtenu : {P.sources_non_fusionnees(FUSIONNE)})")

# Une série de phrases attribuées à UNE SEULE source ne suffit pas : c'est le
# seuil MIN_SOURCES_DISTINCTES_EMPILEES qui garde le motif précis.
UNE_SEULE = {"corps": {"faits": " ".join(
    [f"Selon l’Inserm, le point numéro {i} a été établi par l’étude." for i in range(5)]
), "contexte": "", "nuances": ""}}
verifie("5 phrases attribuées à la même source → pas un empilement",
        not P.sources_non_fusionnees(UNE_SEULE))

# ── 5. Prise de position : injonction vs explication ─────────────────────────
print("\n5. Prise de position (extension du 12/08)")
verifie("« Il est essentiel de renforcer la vigilance » → détecté",
        bool(P.prise_de_position({"resume": "", "corps": {"nuances":
             "Il est essentiel de renforcer la vigilance et les mesures de prévention "
             "pour contrôler la propagation de la rougeole."}})))
verifie("« Il est essentiel de comprendre la différence » → non détecté",
        not P.prise_de_position({"resume": "", "corps": {"nuances":
             "Les deux termes sont souvent confondus, mais il est essentiel de comprendre "
             "la différence entre incidence et prévalence."}}))
# Réserve scientifique standard : c'est le contenu attendu de « Débats et
# nuances », le motif ne doit pas le punir (« nécessaire » volontairement exclu).
verifie("« il est nécessaire de poursuivre les recherches » → non détecté",
        not P.prise_de_position({"resume": "", "corps": {"nuances":
             "Les résultats sont prometteurs, mais il est nécessaire de poursuivre les "
             "recherches pour confirmer l’efficacité du traitement."}}))
# Connecteur français courant, écarté de cliches_ia le 28/07 pour la même
# raison : 50 % du corpus le contient.
verifie("« il est important de noter que » → non détecté",
        not P.prise_de_position({"resume": "", "corps": {"nuances":
             "Il est important de noter que les résultats ne signifient pas que le "
             "traitement guérit la maladie."}}))

print()
if echecs:
    print(f"ÉCHEC — {len(echecs)} test(s) : {', '.join(echecs)}")
    sys.exit(1)
print("Tous les tests passent.")
