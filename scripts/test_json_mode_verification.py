"""Le fact-checker demande au fournisseur un JSON valide, plutôt que de réparer.

── CE QUE LE RUN DU 19/08 A CORRIGÉ DANS MON DIAGNOSTIC ──────────────────────

Le matin, trois `erreur_verification` ont été attribuées au bug du 18/08 (saut
de ligne littéral) et l'échappement des caractères de contrôle a été branché
sur le fact-checker. Le run suivant a montré que c'était le mauvais défaut :

    Invalid control character   → saut de ligne littéral        (corrigé)
    Expecting ',' delimiter     → GUILLEMET DOUBLE non échappé   (le vrai)

Le fact-checker CITE l'article qu'il analyse (« la phrase "X" contredit… ») :
il produit donc des guillemets à l'intérieur de ses propres chaînes JSON. On ne
peut pas réparer ça après coup — rien dans le flux ne dit si un guillemet ouvre
une chaîne ou appartient au texte. C'est pourquoi on contraint la SORTIE au
lieu de rafistoler la LECTURE.
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import verification_legacy as V  # noqa: E402


class _Rep:
    def __init__(self, code, texte, contenu=None):
        self.status_code, self.text = code, texte
        self._c = contenu

    def json(self):
        return {"choices": [{"message": {"content": self._c}}], "usage": {}}


def test_le_defaut_reel_est_le_guillemet_pas_le_saut_de_ligne():
    """Les deux erreurs vues en production sont bien de familles différentes."""
    def erreur(s):
        try:
            json.loads(s)
        except ValueError as e:
            return str(e).split(":")[0]
        return "aucune"
    assert erreur('{"a": "un\ndeux"}').startswith("Invalid control character")
    assert erreur('{"a": "il dit "bonjour" ici", "b": 1}').startswith("Expecting ','")


def test_le_mode_json_est_demande_au_fournisseur():
    V._JSON_MODE[0] = True
    vus = []

    def faux_post(url, headers=None, json=None, timeout=None):
        vus.append(json)
        return _Rep(200, "", '{"conforme": true}')

    with mock.patch.object(V.requests, "post", faux_post):
        V.GROQ_KEYS = ["k"]
        V._llm_call("Réponds en JSON strict.", max_tokens=100)
    assert vus[0].get("response_format") == {"type": "json_object"}, (
        f"le mode JSON n'est pas demandé : {vus[0]}")


def test_un_fournisseur_qui_refuse_l_option_ne_fait_perdre_aucun_sujet():
    """Le repli est la propriété qui compte : une optimisation ne doit JAMAIS
    coûter un article. Un 400 sur `response_format` → nouvel essai sans."""
    V._JSON_MODE[0] = True
    appels = []

    def faux_post(url, headers=None, json=None, timeout=None):
        appels.append(json)
        if "response_format" in json:
            return _Rep(400, '{"error":"unknown parameter response_format"}')
        return _Rep(200, "", '{"conforme": true}')

    with mock.patch.object(V.requests, "post", faux_post):
        V.GROQ_KEYS = ["k"]
        sortie = V._llm_call("Réponds en JSON strict.", max_tokens=100)
    assert sortie == '{"conforme": true}', "le repli n'a pas rendu la réponse"
    assert len(appels) == 2 and "response_format" not in appels[1]
    assert V._JSON_MODE[0] is False, "le refus doit être retenu pour le processus"


def test_un_400_ordinaire_reste_une_erreur():
    """Ne pas confondre « option refusée » et « requête invalide » : un 400 qui
    ne parle pas de response_format doit continuer à lever, sinon on masquerait
    une vraie panne derrière un repli silencieux."""
    V._JSON_MODE[0] = True

    def faux_post(url, headers=None, json=None, timeout=None):
        return _Rep(400, '{"error":"model not found"}')

    with mock.patch.object(V.requests, "post", faux_post):
        V.GROQ_KEYS = ["k"]
        try:
            V._llm_call("Réponds en JSON strict.", max_tokens=100)
        except RuntimeError as e:
            assert "400" in str(e)
            return
    raise AssertionError("un 400 non lié à response_format doit lever")


if __name__ == "__main__":
    test_le_defaut_reel_est_le_guillemet_pas_le_saut_de_ligne()
    test_le_mode_json_est_demande_au_fournisseur()
    test_un_fournisseur_qui_refuse_l_option_ne_fait_perdre_aucun_sujet()
    test_un_400_ordinaire_reste_une_erreur()
    print("OK — JSON contraint à la source, repli sûr si le fournisseur refuse")
