"""Un refus d'ACCÈS ne doit jamais ressortir comme un verdict éditorial.

30/08 : un essai de `mistral-medium-latest` a présenté une clé Google, parce
que le workflow lisait `LLM_API_KEY_ESSAI` en priorité inconditionnelle et que
ce secret contenait encore une clé d'essai Gemini. Trois `401 Invalid API Key`,
affichés comme « 3 sujet(s) sur 3 n'ont pas produit d'article conforme ».

Lu vite, ça dit « ce modèle ne sait pas écrire » d'un modèle JAMAIS interrogé.
C'est le « pire faux signal possible » que le commentaire du 25/08 décrit, sur
un outil dont la raison d'être est de DÉCIDER d'un fournisseur — et il s'est
produit dans l'autre sens que celui qu'on avait prévu.

Même famille que le flux RSS qui répond 200 avec 0 article : l'échec le plus
coûteux est celui qui ressemble à un résultat.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODELE_ESSAI", "mistral-medium-latest")

import essai_fournisseur as E  # noqa: E402


class _Faux(Exception):
    pass


class AuthenticationError(Exception):
    pass


class NotFoundError(Exception):
    pass


def test_401_est_une_panne_d_acces():
    assert E._est_panne_acces(_Faux("Error code: 401 - {'detail': 'Invalid API Key'}"))


def test_403_hors_palier_est_une_panne_d_acces():
    """Le blocage qui a arrêté la production le 29/08 : le modèle existe, la
    clé est valide, mais l'abonnement ne l'autorise pas."""
    assert E._est_panne_acces(_Faux(
        "Error code: 403 - {'message': 'This model is not available in your "
        "subscription tier', 'code': '1910'}"))


def test_le_type_d_exception_suffit():
    """Le SDK peut lever un type dédié sans que le code figure dans le texte."""
    assert E._est_panne_acces(AuthenticationError("clé refusée"))
    assert E._est_panne_acces(NotFoundError("modèle inconnu"))


def test_un_429_n_est_PAS_une_panne_d_acces():
    """LE bord qui compte. Un rate limit est une condition d'exploitation : le
    fournisseur a bien accepté la clé et le modèle. Le classer en panne
    d'accès masquerait un vrai problème de débit."""
    assert not E._est_panne_acces(_Faux("Error code: 429 - rate limit reached"))


def test_une_erreur_de_redaction_reste_un_echec_editorial():
    """Un JSON invalide ou un HORS_PERIMETRE est un vrai verdict : le modèle a
    répondu. Il ne doit pas être absous comme une panne."""
    assert not E._est_panne_acces(ValueError('"HORS_PERIMETRE"'))
    assert not E._est_panne_acces(_Faux("Pas de JSON dans la réponse"))


def test_le_code_de_sortie_distingue_les_deux():
    """2 = rien mesuré, 1 = mesuré et non conforme, 0 = conforme. Un appel
    automatisé doit pouvoir les séparer sans lire le texte."""
    source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "essai_fournisseur.py"), encoding="utf-8").read()
    assert "return 2" in source, (
        "une panne d'accès doit avoir son propre code de sortie, sinon elle "
        "se confond avec un échec éditorial")
    # ⚠ Comparer les PREMIÈRES occurrences serait faux : `main()` rend déjà 1
    # sur « modèle non défini » et « aucun sujet collecté », bien avant le
    # verdict. On ne regarde donc que le bloc de verdict final.
    verdict = source[source.rindex('print("=" * 74)'):]
    assert verdict.index("if pannes:") < verdict.index("if echecs:"), (
        "la panne d'accès doit être testée AVANT le verdict éditorial : "
        "sinon un essai qui n'a rien mesuré rend quand même un compte de "
        "sujets « non conformes »")


def test_le_module_pipeline_n_est_pas_masque_dans_main():
    """Régression du 30/08, dans le correctif même qui devait fiabiliser l'essai.

    `pipeline` est importé sous l'alias `p`. Écrire `for p in pannes` dans
    `main()` rend `p` LOCAL pour toute la fonction, et `p.GROQ_MODEL = MODELE`
    — cinquante lignes plus haut — lève alors UnboundLocalError. Le script
    mourait avant d'avoir interrogé le fournisseur, donc l'essai ne mesurait
    toujours rien : même symptôme que le bug qu'il corrigeait.
    """
    import re
    source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "essai_fournisseur.py"), encoding="utf-8").read()
    alias = re.search(r"^import pipeline as (\w+)", source, re.M)
    assert alias, "l'alias d'import de pipeline a changé — relire ce test"
    nom = alias.group(1)
    corps = source[source.index("def main("):]
    masquage = re.search(rf"^\s+(?:for|with)\s+{nom}\s|^\s+{nom}\s*=[^=]",
                         corps, re.M)
    assert not masquage, (
        f"« {nom} » est réaffecté dans main() : cela masque le module pipeline "
        f"pour TOUTE la fonction — {masquage.group(0).strip() if masquage else ''}")


def test_le_workflow_permet_de_choisir_la_cle():
    """La cause racine : le workflow imposait la clé d'essai. Il doit pouvoir
    présenter la clé de PRODUCTION quand on essaie un autre modèle du MÊME
    fournisseur."""
    wf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      ".github", "workflows", "essai_fournisseur.yml")
    contenu = open(wf, encoding="utf-8").read()
    assert "inputs.cle == 'production'" in contenu, (
        "le workflow ne permet plus de présenter la clé de production : "
        "un essai sur le fournisseur courant rendra un 401")


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
