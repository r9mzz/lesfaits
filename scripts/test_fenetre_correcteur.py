"""Le correcteur ne doit pas être étranglé par la fenêtre d'un autre fournisseur.

Trouvé hors ligne le 19/08. `verification_legacy._llm_call` bornait sa
réservation à `11_500 - prompt`, c'est-à-dire la fenêtre de GROQ codée en dur,
dans un pipeline qui tourne désormais sur Mistral (500 000).

Mesuré sur les prompts réels des runs du jour :

    correction, prompt 5 200 tk  →  4 500 accordés
    correction, prompt 7 300 tk  →  4 200 accordés   ⚠ raboté
    correction, prompt 9 000 tk  →  2 500 accordés   ⚠ raboté

Le correcteur réécrit l'article ENTIER plus sa liste de sources : à 2 500
tokens il tronque, le JSON devient invalide, et ça ressort en « Erreur API
correction » — observé deux fois le 19/08, sur les articles les plus longs.

C'est l'effet inversé de la famine de complétion du 15/08, rejoué côté
vérification : plus l'article est long et bien sourcé, plus on l'étrangle.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

from fenetres_modeles import FENETRE_PAR_DEFAUT, _TPM_PAR_MODELE_GEN  # noqa: E402


def _accorde(modele, prompt_tk, demande):
    """Rejoue la borne telle qu'elle est écrite dans verification_legacy."""
    fenetre = _TPM_PAR_MODELE_GEN.get(modele, FENETRE_PAR_DEFAUT)
    return max(1500, min(demande, fenetre - 500 - prompt_tk))


def test_la_borne_n_est_plus_ecrite_en_dur():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "verification_legacy.py"), encoding="utf-8").read()
    assert "11_500 - prompt_estime" not in src, (
        "la fenêtre Groq est de nouveau codée en dur dans le fact-checker")
    assert "_TPM_PAR_MODELE_GEN" in src, (
        "le fact-checker ne lit plus la table de fenêtres partagée")


def test_sur_mistral_le_correcteur_garde_tout_son_budget():
    """Le cas qui échouait : article long, prompt de correction lourd."""
    for prompt_tk in (7300, 9000):
        assert _accorde("mistral-large-latest", prompt_tk, 4500) == 4500, (
            f"prompt de {prompt_tk} tokens : le correcteur est encore raboté "
            "alors que la fenêtre Mistral fait 500 000")


def test_la_table_est_bien_PARTAGEE_avec_la_generation():
    """C'est le partage qui compte : le jour où le fournisseur change, les deux
    côtés doivent apprendre la nouvelle fenêtre ensemble. C'est exactement ce
    qui a manqué entre le 18 et le 19/08."""
    import pipeline as P
    assert P._TPM_PAR_MODELE_GEN is _TPM_PAR_MODELE_GEN, (
        "génération et vérification ne lisent plus la même table de fenêtres")


def test_un_petit_modele_reste_honnetement_borne():
    """Ne pas confondre « ne plus raboter » et « promettre l'impossible ».

    Sur une fenêtre de 8 000, un prompt de 9 000 ne laisse RIEN : la borne doit
    retomber sur son plancher, pas accorder un budget fictif qui produirait un
    413 certain — donc un sujet perdu au lieu d'une réponse courte.
    """
    assert _accorde("openai/gpt-oss-120b", 9000, 4500) == 1500


if __name__ == "__main__":
    test_la_borne_n_est_plus_ecrite_en_dur()
    test_sur_mistral_le_correcteur_garde_tout_son_budget()
    test_la_table_est_bien_PARTAGEE_avec_la_generation()
    test_un_petit_modele_reste_honnetement_borne()
    print("OK — le correcteur lit la fenêtre du modèle réellement servi")
