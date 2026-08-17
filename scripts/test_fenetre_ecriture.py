"""La fenêtre TPM doit toujours laisser de quoi ÉCRIRE.

Mesuré le 15/08 : dans la configuration nominale (10 sources × 950 caractères
d'extrait + 7 000 caractères de contenu principal), le prompt de génération
atteignait ~12 900 tokens sur une fenêtre de 12 000. `_groq_call` retombait
alors sur son plancher de 200 tokens réservés — un article JSON de 800 mots en
demande environ 2 000. La complétion était coupée PAR CONSTRUCTION, et l'effet
était inversé : plus le sujet était bien sourcé, moins il restait de place pour
l'écrire.

Ces tests verrouillent les trois propriétés du correctif, sans réseau ni jeton.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402


def _capturer(n_sources, snippet, contenu, article_type="actu"):
    """Construit un vrai prompt de génération et renvoie (prompt, réservation)."""
    vus = []

    def faux_groq(api_key, messages, max_tokens=3500):
        tpm = P._TPM_PAR_MODELE_GEN.get(P.GROQ_MODEL, 12_000)
        prompt = int(sum(len(m.get("content", "")) for m in messages) / 3.3)
        vus.append((prompt, max(200, min(max_tokens, tpm - 500 - prompt))))
        raise RuntimeError("interception — aucun appel réseau")

    vrai = P._groq_call
    P._groq_call = faux_groq
    try:
        P.generate(
            "y" * contenu, "societe",
            [{"url": f"https://exemple{i}.fr/doc-{i}", "title": f"Document {i}",
              "snippet": "x" * snippet, "institution": f"Inst {i}"}
             for i in range(n_sources)],
            article_type=article_type,
        )
    except Exception:
        pass
    finally:
        P._groq_call = vrai
    assert vus, "le prompt n'a jamais été construit"
    return vus[0]


def test_configuration_nominale_laisse_de_quoi_ecrire():
    """Le cas qui échouait : 10 sources profondes + contenu long."""
    _, reste = _capturer(10, 950, 7000)
    # Ce test vérifie que le MÉCANISME de réservation opère : sans lui, ce cas
    # retombait à 200, le plancher de `_groq_call`. Le seuil est délibérément
    # bas — c'est `test_le_prompt_systeme_ne_grossit_pas_en_silence` qui garde
    # la valeur ABSOLUE, en plafonnant ce qui mange la fenêtre.
    #
    # ⚠ Repère à ne pas perdre de vue : les complétions ayant réellement produit
    # un article publiable valaient 1 423 et 1 505 tokens. Au 17/08 le cas
    # nominal à 10 sources tombe à 1 403 — SOUS ces deux valeurs, après les
    # +292 tokens de règle éditoriale ajoutés le 15/08. Le mécanisme fait son
    # travail (8× mieux qu'avant), mais la fenêtre de 12 000 ne laisse plus de
    # marge : le prochain ajout au prompt se paie en articles tronqués.
    assert reste > 1200, (
        f"réservation d'écriture de {reste} tokens — un article JSON en demande "
        "~2 000. C'est le défaut mesuré le 15/08, il est revenu."
    )
    assert reste != 200, "le plancher de _groq_call est atteint : rien n'a été réservé"


def test_le_sujet_bien_source_n_est_pas_puni():
    """Propriété inversée : richesse documentaire ≠ moins de place pour écrire."""
    _, riche = _capturer(10, 950, 7000)
    _, pauvre = _capturer(6, 380, 2500)
    assert riche > 1200 and pauvre > 1200
    # On n'exige pas l'égalité — la coupe est graduelle — mais l'écart ne doit
    # plus être un ordre de grandeur, comme c'était le cas (200 contre 2 342).
    assert riche > pauvre / 2, (
        f"le sujet riche ne garde que {riche} tokens contre {pauvre} au sujet "
        "pauvre : la fenêtre punit encore le bon sourcing"
    )


def test_le_nombre_de_sources_n_est_jamais_reduit():
    """La coupe porte sur la PROFONDEUR des extraits, jamais sur le sourcing.

    Réduire le nombre de sources injectées ferait échouer le garde-fou « ≥1
    primaire OU ≥2 secondaires » sur des sujets valides : ce serait affaiblir
    un contrôle pour tenir un budget, exactement ce que la charte interdit.
    """
    noms = []

    def faux_groq(api_key, messages, max_tokens=3500):
        noms.append(sum(m.get("content", "").count("--- SOURCE ") for m in messages))
        raise RuntimeError("interception")

    vrai = P._groq_call
    P._groq_call = faux_groq
    try:
        P.generate("y" * 7000, "societe",
                   [{"url": f"https://exemple{i}.fr/d{i}", "title": f"D{i}",
                     "snippet": "x" * 950, "institution": f"I{i}"} for i in range(10)])
    except Exception:
        pass
    finally:
        P._groq_call = vrai
    # 10 sources fournies + la source RSS d'origine éventuelle : au moins 10.
    assert noms and noms[0] >= 10, f"{noms} sources injectées au lieu de 10"


def test_la_reservation_suit_le_tpm_du_modele():
    """Fenêtre plus large = plus aucune coupe. Rien à re-régler en offre payante."""
    modele = P.GROQ_MODEL
    table = dict(P._TPM_PAR_MODELE_GEN)
    P._TPM_PAR_MODELE_GEN[modele] = 60_000
    try:
        prompt, reste = _capturer(10, 950, 7000)
    finally:
        P._TPM_PAR_MODELE_GEN.clear()
        P._TPM_PAR_MODELE_GEN.update(table)
    assert prompt > 11_000, (
        f"prompt de {prompt} tokens : la matière a été coupée alors que la "
        "fenêtre était large — la réservation ne lit pas le TPM du modèle"
    )
    assert reste > 2000


def test_le_prompt_systeme_ne_grossit_pas_en_silence():
    """Chaque règle ajoutée au prompt retire de la place pour écrire.

    Le 15/08, une consigne de mise en paragraphes — utile, la consigne manquait
    vraiment — a coûté +470 tokens sur une fenêtre déjà à zéro, sans que rien ne
    le signale. C'est la panne silencieuse : le prompt grandit, la complétion
    rétrécit, et personne ne fait le lien avec les articles tronqués.

    Ce plafond n'interdit pas d'enrichir le prompt. Il oblige à le faire
    SCIEMMENT : relever la constante ci-dessous est une décision, et le diff dit
    combien de tokens d'écriture ont été échangés contre la nouvelle règle.

    Taux de change mesuré (voir CLAUDE.md) : 100 tokens ajoutés au prompt
    valent 30 à 40 mots que l'article ne pourra plus contenir. La question à se
    poser en relevant le plafond est donc « cette règle vaut-elle 30 mots
    d'article ? » — elle a souvent une bonne réponse, mais elle doit être posée.
    """
    # Historique des relèvements — chaque ligne dit ce qui a été échangé :
    #   6 700  15/08  état initial du plafond (prompt à 6 601)
    #   7 000  17/08  +292 tk pour « interdire la chaîne monotone [Acteur] a
    #                 [verbe] répétée » (0de58664, exemple de Nahil à l'appui).
    #                 Prix : ~90 mots d'article. La règle vise un défaut de
    #                 rédaction réel et constaté ; elle les vaut. Effet mesuré
    #                 sur la fenêtre nominale : 1 604 → 1 403 tokens d'écriture.
    plafond = 7_000   # tokens — état du 17/08 : 6 893
    _tpm = P._TPM_PAR_MODELE_GEN.get(P.GROQ_MODEL, 12_000)
    for nom, prompt in (("actu", P.SYSTEM_PROMPT), ("brève", P.SYSTEM_PROMPT_BREVE)):
        cout = int(len(prompt) / 3.3)
        assert cout <= plafond, (
            f"le prompt système {nom} pèse {cout} tokens (plafond {plafond}), "
            f"soit {cout / _tpm:.0%} de la fenêtre de {_tpm} — autant de moins "
            "pour écrire l'article. Si l'ajout est justifié, relever le plafond "
            "dans ce test en disant ce qu'on échange."
        )


if __name__ == "__main__":
    test_le_prompt_systeme_ne_grossit_pas_en_silence()
    test_configuration_nominale_laisse_de_quoi_ecrire()
    test_le_sujet_bien_source_n_est_pas_puni()
    test_le_nombre_de_sources_n_est_jamais_reduit()
    test_la_reservation_suit_le_tpm_du_modele()
    print("OK — la fenêtre TPM garde toujours de quoi écrire, sans toucher au sourcing")
