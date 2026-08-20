"""Ce journal ne contacte personne — le texte ne doit pas prétendre le contraire.

Sorti d'un brouillon Mistral le 20/08 :

    « Santé publique France, CONTACTÉE POUR CLARIFICATION, indique que
      l'attribution définitive de ces décès à la canicule nécessitera… »

Aucun être humain ne travaille ici : le pipeline lit des flux RSS et des pages
web. Cette phrase invente un acte de journalisme qui n'a pas eu lieu.

Ce n'est pas une fabrication sur le FAIT, c'est une fabrication sur NOTRE
MÉTHODE — donc sur la seule chose que le site demande au lecteur de croire, et
que la section « Pourquoi cet article a été publié » revendique explicitement
(« il n'y a jamais de relecture humaine »). Plus grave qu'une attribution
fantôme.

Mesuré avant ajout : 0 occurrence sur les 177 articles publiés, 2 dans le
journal, toutes deux du 20/08. C'est un risque APPARU avec le nouveau
rédacteur, pas un défaut historique — et le garde-fou ne peut donc rétrograder
aucun article du type de ceux qu'on a publiés.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402


def _art(faits, resume=None):
    return {"corps": {"faits": faits, "contexte": "", "nuances": ""},
            "resume": resume or []}


def test_le_cas_reel_du_20_08_est_attrape():
    a = _art("Santé publique France, contactée pour clarification, indique que "
             "l'attribution définitive nécessitera une analyse des certificats.")
    assert P.reportage_invente(a), "la phrase du brouillon Mistral passe encore"


def test_les_variantes_de_la_meme_pretention():
    for phrase in (
        "L'ANSSI, contactée par notre rédaction, n'a pas répondu.",
        "Le ministère, joint par notre rédaction, confirme l'information.",
        "L'organisme, interrogé par la rédaction, précise le calendrier.",
        "Nous avons contacté l'agence, sans réponse à ce jour.",
        "Selon les informations de notre rédaction, le texte sera présenté.",
    ):
        assert P.reportage_invente(_art(phrase)), f"non détecté : {phrase}"


def test_une_attribution_normale_n_est_pas_touchee():
    """Le garde-fou vise la PRÉTENTION à un acte de reportage, pas l'attribution.

    Citer un organisme est le fonctionnement normal et obligatoire du journal :
    confondre les deux rendrait le contrôle inutilisable.
    """
    for phrase in (
        "Santé publique France indique dans son bulletin du 19 août que [1].",
        "Selon l'ANSSI, 3 586 événements de sécurité ont été recensés [2].",
        "Le ministère a annoncé la mesure lors d'une conférence de presse [3].",
        "L'agence a été contactée par le Sénat en juillet [4].",
    ):
        assert not P.reportage_invente(_art(phrase)), f"faux positif : {phrase}"


def test_le_chapeau_est_couvert_aussi():
    """Le chapeau est la première chose lue — il ne peut pas être un angle mort."""
    a = _art("Rien ici.", resume=["L'agence, contactée par notre rédaction, confirme."])
    assert P.reportage_invente(a)


def test_le_controle_est_rejoue_apres_la_passe_3():
    """La passe 3 réécrit le texte et peut réintroduire ce qu'elle a nettoyé.

    Leçon du tableau du 03/08 : tout contrôle placé avant `verifier_article`
    doit être considéré comme invalidé. Celui-ci est un rejet SEC — retirer
    « contactée pour clarification » laisserait une déclaration attribuée à un
    organisme qui n'a rien déclaré, donc il n'est pas réparable.
    """
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "pipeline.py"), encoding="utf-8").read()
    assert "ACTE DE REPORTAGE INVENTÉ APRÈS CORRECTION" in src, (
        "le contrôle n'est plus rejoué après la passe de correction")
    assert "reportage_invente(art)" in src


if __name__ == "__main__":
    test_le_cas_reel_du_20_08_est_attrape()
    test_les_variantes_de_la_meme_pretention()
    test_une_attribution_normale_n_est_pas_touchee()
    test_le_chapeau_est_couvert_aussi()
    test_le_controle_est_rejoue_apres_la_passe_3()
    print("OK — aucun acte de reportage inventé ne peut être publié")
