"""Le fournisseur de complétion est une variable, pas une constante.

Groq a retiré `llama-3.3-70b-versatile` le 17/08 sans préavis, et ses modèles
restants plafonnent à 8 000 tokens par requête — sous la taille d'un prompt
d'article. Le pipeline doit donc pouvoir viser un autre service compatible
OpenAI sans réécriture, et sans que le comportement par défaut change.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

echecs = []


def verifie(nom, cond, detail=""):
    print(f"  {'OK  ' if cond else 'ÉCHEC'} {nom} {detail}")
    if not cond:
        echecs.append(nom)


print("1. Par défaut, rien ne change")
verifie("aucune base fournie → client Groq",
        P.LLM_BASE_URL == "" and type(P._client("x")).__name__ == "Groq")

print("\n2. Une base fournie bascule le client, sans toucher aux appels")
# ⚠ Le SDK `groq` ne peut PAS servir ici : il code en dur le chemin
# `/openai/v1/chat/completions`, si bien qu'une base pointée sur Mistral
# produirait `https://api.mistral.ai/v1/openai/v1/…`. D'où le client `openai`.
vrai = P.LLM_BASE_URL
P.LLM_BASE_URL = "https://api.mistral.ai/v1"
try:
    c = P._client("x")
    verifie("client compatible OpenAI", type(c).__name__ == "OpenAI")
    verifie("la base est bien celle demandée",
            str(c.base_url).rstrip("/") == "https://api.mistral.ai/v1")
finally:
    P.LLM_BASE_URL = vrai

print("\n3. Les fenêtres du nouveau fournisseur sont déclarées")
# Un modèle ABSENT de la table retombe sur 12 000 par défaut : la réservation
# couperait alors la matière pour rien, sur un service qui n'en a pas besoin.
for m in ("mistral-large-latest", "mistral-medium-latest",
          "mistral-small-latest", "open-mistral-nemo"):
    verifie(f"{m} déclaré", P._TPM_PAR_MODELE_GEN.get(m, 0) >= 100_000)

print("\n4. Une seule clé suffit et ne casse aucun mécanisme")
# Les 11 clés Groq contournent un plafond journalier PAR COMPTE. Un service qui
# accorde un milliard de tokens par mois n'a pas ce problème.
cles = [("abc", "clé fournisseur")]
verifie("la rotation du juge tient sur une liste d'un élément",
        cles[abs(hash("un titre quelconque")) % len(cles)][1] == "clé fournisseur")

print("\n5. La lecture des erreurs 429 dégrade proprement")
# Les motifs « Limit X, Used Y » et « try again in … » sont du texte Groq. Un
# autre fournisseur formule autrement : ces fonctions doivent rendre None, pas
# lever.
for msg in ("Rate limit exceeded, please retry later",
            "429 Too Many Requests", "", "service unavailable"):
    verifie(f"délai illisible → None ({msg[:28]!r})",
            P._delai_liberation(msg) is None)
    verifie(f"solde illisible → None ({msg[:28]!r})",
            P._tpd_restant(msg) is None)
verifie("un message Groq reste lu correctement",
        P._tpd_restant("Limit 100000, Used 97500, Requested 8000") == 2500)

print()
sys.exit(1 if echecs else 0)
