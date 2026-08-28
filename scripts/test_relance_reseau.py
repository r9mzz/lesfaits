"""Un timeout réseau ne doit pas coûter un article déjà écrit.

Run 287 (27/08) : 11 « Read timed out (read timeout=180) » sur api.mistral.ai,
7 articles perdus en `erreur_verification`. Le fail-closed a bien joué son rôle
— rien n'est publié sans fact-check — mais l'article était écrit et payé, et il
est mort sur une latence du fournisseur. Le run 290, deux heures plus tard, n'a
eu que 3 timeouts : la panne est transitoire, donc réessayable.

⚠ CE QUI EST VERROUILLÉ ICI, c'est autant la relance que sa BORNE : on ne
relance jamais une RÉPONSE HTTP. Un 402, un 429, un 400 sont des décisions du
fournisseur, chacune traitée par son propre chemin ; les relancer en aveugle
masquerait la panne et ferait repayer l'appel.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests  # noqa: E402
import verification_legacy as V  # noqa: E402


class _Reponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.text = "{}"


def test_relance_apres_un_timeout():
    appels = []

    def faux_post(url, **kw):
        appels.append(url)
        if len(appels) == 1:
            raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)")
        return _Reponse()

    with mock.patch.object(V.requests, "post", faux_post), \
         mock.patch.object(V.time, "sleep", lambda _: None):
        r = V._post_avec_relance("https://api.mistral.ai/v1/chat/completions")
    assert r.status_code == 200
    assert len(appels) == 2, f"une relance attendue, {len(appels)} appel(s)"


def test_relance_apres_une_erreur_de_connexion():
    appels = []

    def faux_post(url, **kw):
        appels.append(url)
        if len(appels) < 3:
            raise requests.exceptions.ConnectionError("Connection error.")
        return _Reponse()

    with mock.patch.object(V.requests, "post", faux_post), \
         mock.patch.object(V.time, "sleep", lambda _: None):
        assert V._post_avec_relance("https://x").status_code == 200
    assert len(appels) == 3


def test_l_echec_persistant_remonte_toujours():
    """La relance ne doit pas avaler une panne réelle : après épuisement des
    essais, l'exception d'origine remonte et le fail-closed rejette."""
    def faux_post(url, **kw):
        raise requests.exceptions.ReadTimeout("Read timed out.")

    with mock.patch.object(V.requests, "post", faux_post), \
         mock.patch.object(V.time, "sleep", lambda _: None):
        try:
            V._post_avec_relance("https://x")
        except requests.exceptions.ReadTimeout:
            return
    raise AssertionError("un timeout persistant doit remonter, pas être avalé")


def test_une_reponse_http_n_est_jamais_relancee():
    """LE bord qui compte. Un 402 est une décision du fournisseur : un seul
    appel, la réponse est rendue telle quelle à la rotation de clés."""
    appels = []

    def faux_post(url, **kw):
        appels.append(url)
        return _Reponse(402)

    with mock.patch.object(V.requests, "post", faux_post), \
         mock.patch.object(V.time, "sleep", lambda _: None):
        r = V._post_avec_relance("https://x")
    assert r.status_code == 402
    assert len(appels) == 1, (
        f"un 402 ne doit JAMAIS être relancé ({len(appels)} appels) : la "
        "rotation de clés doit le voir")


def test_le_client_de_generation_est_configure():
    """Côté rédaction, la relance vient du SDK : la valeur doit être explicite
    dans le code, jamais héritée d'un défaut de bibliothèque."""
    os.environ.setdefault("GROQ_MODEL_OVERRIDE", "mistral-large-latest")
    import pipeline  # noqa: E402
    assert pipeline._RELANCES_FOURNISSEUR >= 2
    assert pipeline._TIMEOUT_FOURNISSEUR_S >= 120, (
        "un timeout court transformerait des générations valides en échecs")
    client = pipeline._client("cle-de-test")
    assert client.max_retries == pipeline._RELANCES_FOURNISSEUR


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
