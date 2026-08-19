"""Un saut de ligne littéral dans une chaîne JSON ne doit plus perdre l'article.

── DÉFAUT DU 18/08, ET IL VENAIT DE NOUS ────────────────────────────────────

La norme JSON interdit un saut de ligne brut dans une chaîne : il doit être
écrit `\n`. Or le prompt exige depuis le 15/08 une MISE EN PARAGRAPHES du corps
— on demandait donc au modèle de produire ce qui casse notre propre lecture.

Llama 3.3 échappait ces sauts de ligne, Mistral les écrit tels quels. La panne
était silencieuse : `json.loads` échoue, le repli remonte au dernier préfixe
parsable, et l'article revient sans `corps` ni `sources`. Mesuré sur l'essai
Mistral — `fin=stop`, 1 583 tokens produits, ~250 récupérés. Le texte avait été
écrit ; il était perdu à la lecture.
"""
import json
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


ARTICLE = '''{
  "titre": "Le kuru, une maladie a prions",
  "resume": ["Une phrase.", "Une autre."],
  "corps": {
    "faits": "Premier paragraphe du texte.
Second paragraphe, apres un saut de ligne litteral.",
    "contexte": "Historique du sujet.",
    "nuances": ""
  },
  "sources": [{"titre": "OMS", "url": "https://who.int"}]
}'''

print("1. Le cas qui perdait l'article")
try:
    json.loads(ARTICLE)
    brut_ok = True
except json.JSONDecodeError:
    brut_ok = False
verifie("sans échappement, la lecture échoue (c'est bien la cause)", not brut_ok)

art = json.loads(P._echapper_controles_json(ARTICLE))
verifie("après échappement, le corps est là", "corps" in art)
verifie("après échappement, les sources sont là", bool(art.get("sources")))
verifie("les paragraphes sont PRÉSERVÉS, pas écrasés",
        "\n" in art["corps"]["faits"],
        f"({art['corps']['faits'][:40]!r})")

print("\n2. Le JSON lui-même n'est pas corrompu")
# Un `replace` global des sauts de ligne casserait la mise en forme du document
# JSON. On ne doit toucher qu'à l'INTÉRIEUR des chaînes.
propre = '{\n  "a": "sans saut",\n  "b": 12\n}'
verifie("un JSON déjà valide reste lisible",
        json.loads(P._echapper_controles_json(propre)) == {"a": "sans saut", "b": 12})

print("\n3. Les guillemets échappés ne trompent pas le suivi d'état")
# Si `\"` était compté comme une fin de chaîne, tout le suivi se décalerait et
# les sauts de ligne du document seraient échappés à tort.
avec_guillemets = '{"citation": "il a dit \\"oui\\" hier",\n "b": 1}'
verifie("chaîne contenant des guillemets échappés",
        json.loads(P._echapper_controles_json(avec_guillemets))["citation"]
        == 'il a dit "oui" hier')

print("\n4. Tabulations et retours chariot aussi")
verifie("tabulation littérale dans une chaîne",
        json.loads(P._echapper_controles_json('{"a": "un\tdeux"}'))["a"] == "un\tdeux")

print("\n5. Le chemin complet d'extraction rend bien l'article")
# C'est ce qui compte : pas la fonction isolée, mais ce que `generate()` obtient.
vus = []


def faux_groq(api_key, messages, max_tokens=3500):
    return ARTICLE


vrai = P._groq_call
P._groq_call = faux_groq
try:
    art2 = P.generate("y" * 2000, "societe",
                      [{"url": f"https://ex{i}.fr/d{i}", "title": f"D{i}",
                        "snippet": "x" * 400, "institution": f"I{i}"} for i in range(6)])
except Exception as e:  # noqa: BLE001
    art2 = {"erreur": f"{type(e).__name__}: {e}"}
finally:
    P._groq_call = vrai
verifie("generate() rend un corps non vide",
        bool((art2.get("corps") or {}).get("faits")),
        f"({str(art2)[:80]})")

print()


# ── 6. Le FACT-CHECKER lit le même JSON que la génération ────────────────────
#
# Le correctif du 18/08 n'avait été posé que sur `pipeline.py`. Le run du 19/08
# a payé cette asymétrie : `[VERIF] Erreur API détection (Expecting ','
# delimiter…)` trois fois, statut `erreur_verification`, donc rejet — des
# articles ayant passé TOUTE la chaîne éditoriale, perdus faute de pouvoir lire
# le verdict qui les concernait. Le rapport de vérification est de la prose
# longue : c'est le texte le plus exposé aux sauts de ligne littéraux.
print("\n6. Le fact-checker lit le JSON aussi bien que la génération")

import verification_legacy as V  # noqa: E402

_RAPPORT = '''```json
{"problemes": [{"type": "chiffre_errone", "description": "Le résumé dit 42 %,
alors que la source [1] dit 47 %.

Second paragraphe de l'explication."}], "conforme": false}
```'''
_rap = V._extract_json(_RAPPORT)
assert _rap["problemes"][0]["type"] == "chiffre_errone"
assert "\n" in _rap["problemes"][0]["description"], (
    "les sauts de ligne du rapport doivent être PRÉSERVÉS, pas supprimés"
)
print("  OK   rapport de fact-check avec sauts de ligne littéraux : lu")

_sans_balise = '{"conforme": true, "note": "ligne un\nligne deux"} puis du texte'
assert V._extract_json(_sans_balise)["note"] == "ligne un\nligne deux"
print("  OK   même parade sur le chemin sans balises ```")

# La fonction doit être LA MÊME des deux côtés : c'est ce partage qui empêche
# qu'un correctif ne profite qu'à un seul lecteur, comme entre le 18 et le 19/08.
assert V._echapper_controles_json is P._echapper_controles_json, (
    "génération et vérification n'échappent plus le JSON avec la même fonction"
)
print("  OK   génération et vérification partagent la même fonction")


sys.exit(1 if echecs else 0)
