# -*- coding: utf-8 -*-
"""Fenêtre par modèle — partagée entre la génération et la vérification.

Cette table vivait dans `pipeline.py` seul, et `verification_legacy.py` portait
en dur la valeur Groq (11 500). Conséquence mesurée le 19/08 : sur les articles
les plus longs, la réservation du CORRECTEUR tombait à 2 500 tokens alors qu'il
doit réécrire l'article entier plus ses sources. Il tronquait, le JSON devenait
invalide, et ça ressortait en « Erreur API correction ».

Effet inversé, comme la famine de complétion du 15/08 : plus l'article est long
et bien sourcé, plus le correcteur est étranglé. Le jour où le fournisseur
change, les deux côtés doivent apprendre la nouvelle fenêtre ensemble — d'où
ce module, qui ne dépend de rien et ne crée aucun cycle d'import.
"""

FENETRE_PAR_DEFAUT = 12_000

_TPM_PAR_MODELE_GEN = {
    "llama-3.3-70b-versatile": 12_000,
    "openai/gpt-oss-120b": 8_000,
    "openai/gpt-oss-20b": 8_000,
    "qwen/qwen3.6-27b": 8_000,
    "llama-3.1-8b-instant": 6_000,
    # Relevé sur la grille « Free Plan Limits » de Groq le 17/08, après le
    # retrait de llama-3.3-70b : ce sont les DEUX seules entrées de l'offre
    # gratuite dont la fenêtre laisse tourner le format long. 70 000 TPM, et
    # surtout TPD affiché « — » : aucun plafond journalier.
    #
    #   modèle                    TPM     prompt nominal   reste pour ÉCRIRE
    #   llama-3.3-70b (retiré)  12 000       10 021             1 479
    #   gpt-oss-120b / qwen      8 000       10 021               200
    #   groq/compound           70 000       13 355             3 500
    #
    # À 70 000, la matière n'est plus coupée du tout (prompt complet, 10 × 950
    # caractères) et la réservation bute sur NOTRE plafond, plus sur la fenêtre.
    #
    # ⚠ AVANT DE LES CHOISIR — ce ne sont pas des modèles nus mais le système
    # agentique de Groq, qui dispose d'outils côté serveur (recherche web).
    # Un modèle qui peut aller chercher un fait ailleurs peut introduire dans
    # l'article une information ABSENTE des extraits fournis : c'est la règle 5
    # de la charte, celle sur laquelle tout le reste repose. À vérifier sur un
    # run contrôlé avant d'en faire le modèle par défaut, jamais à supposer.
    # ⚠ 8 000, PAS les 70 000 de la grille tarifaire. Mesuré le 17/08 : Groq
    # facture `groq/compound` sur le compteur d'`openai/gpt-oss-120b`, comme
    # le dit son propre refus — « Rate limit reached for model
    # openai/gpt-oss-120b … on tokens per minute (TPM): Limit 8000 ». Compound
    # n'est pas un modèle mais un système bâti dessus : il hérite du plafond
    # et n'y échappe pas. Déclarer 70 000 a fait envoyer des requêtes de
    # 17 000 tokens, refusées 40 fois sur 40 en « 413 Request Entity Too
    # Large ». C'est la cause des zéro article du run de 18h58.
    # Mistral, palier gratuit : 500 000 tokens/minute et 1 milliard/mois — soit
    # 62 fois la fenêtre de Groq. Nos requêtes d'article (~11 900 tokens) y
    # pèsent 2 % : la réservation d'écriture ne coupe alors plus rien, ce qui
    # est le but. ⚠ Un modèle ABSENT de cette table retombe sur 12 000 par
    # défaut dans le runtime historique. Le banc A/B, lui, refuse désormais de
    # comparer un modèle dont la fenêtre n'a pas été vérifiée : une valeur
    # supposée modifierait la quantité de matière fournie et fausserait le
    # verdict éditorial.
    "mistral-large-latest": 500_000,
    "mistral-medium-latest": 500_000,
    "mistral-small-latest": 500_000,
    "open-mistral-nemo": 500_000,
    "groq/compound": 8_000,
    "groq/compound-mini": 8_000,
}


# ── FENÊTRE D'ESSAI — mesure seulement, jamais la production ────────────────
# `FENETRE_ESSAI` permet de donner à UN essai de fournisseur la fenêtre qu'on
# suppose être la sienne, sans l'écrire dans la table partagée. Pour éviter
# qu'une variable d'environnement résiduelle ne modifie la production, elle
# n'est honorée que si le workflow d'essai pose aussi ESSAI_FOURNISSEUR=1.
def fenetre_essai() -> int | None:
    """Fenêtre imposée pour un essai explicite, sinon None.

    `FENETRE_ESSAI` seule ne doit jamais influencer la production. Le garde
    `ESSAI_FOURNISSEUR=1` rend le canal opt-in et limite sa portée au workflow
    de diagnostic. Une valeur illisible ou non positive est ignorée.
    """
    import os
    if (os.getenv("ESSAI_FOURNISSEUR", "") or "").strip() != "1":
        return None
    brut = (os.getenv("FENETRE_ESSAI", "") or "").strip()
    if not brut:
        return None
    try:
        valeur = int(brut)
    except ValueError:
        print(f"  [ESSAI] FENETRE_ESSAI illisible ({brut!r}) — ignorée")
        return None
    return valeur if valeur > 0 else None
