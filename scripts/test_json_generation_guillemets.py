"""Un guillemet de citation ne doit pas amputer l'article de 97 % de son corps.

── TROUVÉ HORS LIGNE LE 19/08, sans dépenser un jeton ────────────────────────

Le rédacteur CITE des déclarations (« l'ARS a déclaré : "la source n'est pas
identifiée" »). Il produit donc des guillemets DOUBLES à l'intérieur de ses
chaînes JSON, ce que la norme interdit sans échappement.

Mesuré sur le vrai chemin de `generate()`, même article, un seul guillemet de
différence :

    citation SANS guillemets  →  648 mots · faits + contexte + nuances complets
    citation AVEC guillemets  →   17 mots · contexte et nuances ENTIÈREMENT perdus

Le repli de `_extract_json` récupère le dernier préfixe parsable : il rend donc
un article amputé, SANS lever d'erreur. C'est l'origine des « Premier jet à
104 / 118 / 137 mots » des runs du 19/08, lus comme « Mistral écrit court »,
convertis en brève puis rejetés. Le diagnostic éditorial était faux : la panne
est à la lecture, pas à l'écriture.

Même famille que le bug du 18/08 (saut de ligne littéral) et que celui du
fact-checker (guillemet). Trois fois le même mécanisme : on demande au modèle
d'écrire du texte riche DANS du JSON, et le texte riche casse le JSON.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

_SOURCES = [{"url": f"https://exemple{i}.fr/d", "title": f"D{i}",
             "snippet": "x" * 400, "institution": f"Inst {i}"} for i in range(6)]


def _article_json(faits: str) -> str:
    return ('{"titre": "Legionellose en Savoie : 46 cas recenses depuis juin",'
            '"resume": ["L ARS a recense 46 cas.", "Trois personnes sont decedees."],'
            '"angle_reponse": "Faut-il s inquieter ?", "slug": "legionellose-savoie",'
            '"titre_faits": "Les faits", "image_keyword": "hopital",'
            '"corps": {"faits": "' + faits + '",'
            '"contexte": "' + "Historique de la legionellose dans la region. " * 35 + '",'
            '"nuances": "' + "Limites des donnees disponibles. " * 25 + '"},'
            '"sources": [{"url": "https://sante.gouv.fr/a", "titre": "ARS",'
            ' "institution": "ARS"}]}')


def _mots_rendus(reponse_brute: str) -> int:
    def faux(api_key, messages, max_tokens=3500):
        return reponse_brute
    vrai, P._groq_call = P._groq_call, faux
    try:
        a = P.generate("contenu source " * 300, "sante", list(_SOURCES))
    finally:
        P._groq_call = vrai
    c = a.get("corps") or {}
    return len(" ".join([" ".join(a.get("resume") or []), c.get("faits", ""),
                         c.get("contexte", ""), c.get("nuances", "")]).split())


def test_le_mode_json_est_demande_a_la_generation():
    """La parade est de contraindre la SORTIE, pas de deviner à la lecture."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "pipeline.py"), encoding="utf-8").read()
    deb = src.index("def _groq_call(")
    corps = src[deb:deb + 4000]
    assert 'response_format={"type": "json_object"}' in corps, (
        "la génération ne demande plus un JSON garanti : le guillemet de "
        "citation recommencera à amputer les articles")
    assert "repli sur le mode texte" in corps, (
        "aucun repli si le fournisseur refuse l'option — une optimisation ne "
        "doit jamais coûter un sujet")


def test_l_ampleur_de_la_perte_est_bien_celle_mesuree():
    """Trace du défaut, pour qu'il reste reconnaissable s'il revient.

    On ne teste pas que le guillemet est réparé — il ne l'est pas, et c'est
    assumé : la réparation se fait en amont, côté fournisseur. On verrouille
    le CONSTAT, parce que c'est lui qui a été mal lu pendant deux runs.
    """
    citation = ("Le prefet a declare : \"la source n'est pas identifiee\" [1]. "
                + "Un paragraphe de contenu factuel et chiffre. " * 35)
    sans = ("Le prefet a declare que la source n'est pas identifiee [1]. "
            + "Un paragraphe de contenu factuel et chiffre. " * 35)
    complet = _mots_rendus(_article_json(sans))
    ampute = _mots_rendus(_article_json(citation))
    assert complet > 400, f"l'article de référence ne fait que {complet} mots"
    assert ampute < complet / 4, (
        f"le guillemet non échappé ne tronque plus ({ampute} contre {complet} "
        "mots) — tant mieux, mais ce test décrivait le défaut : le vérifier")


def test_la_porte_de_sortie_editoriale_survit_au_mode_json():
    """« réponds uniquement HORS_PERIMETRE » est un REFUS ÉDITORIAL.

    En mode `json_object`, le modèle ne peut plus répondre en texte brut : il
    emballe le marqueur. S'il n'était plus reconnu, un refus correct serait
    compté en panne technique — le défaut exact corrigé le 30/07.
    """
    for enveloppe in (
        'HORS_PERIMETRE',
        '{"reponse": "HORS_PERIMETRE"}',
        '{"statut": "HORS_PERIMETRE", "raison": "sources insuffisantes pour '
        'etablir un evenement date des dernieres 48 heures"}',
    ):
        def faux(api_key, messages, max_tokens=3500, _e=enveloppe):
            return _e
        vrai, P._groq_call = P._groq_call, faux
        try:
            P.generate("contenu " * 300, "sante", list(_SOURCES))
        except ValueError:
            pass  # attendu : refus éditorial
        except Exception as e:
            raise AssertionError(
                f"« {enveloppe[:40]} » rendu en {type(e).__name__} au lieu d'un "
                "refus éditorial") from e
        else:
            raise AssertionError(f"« {enveloppe[:40]} » n'a PAS été reconnu "
                                 "comme HORS_PERIMETRE")
        finally:
            P._groq_call = vrai


if __name__ == "__main__":
    test_le_mode_json_est_demande_a_la_generation()
    test_l_ampleur_de_la_perte_est_bien_celle_mesuree()
    test_la_porte_de_sortie_editoriale_survit_au_mode_json()
    print("OK — JSON contraint à la génération, refus éditorial préservé")
