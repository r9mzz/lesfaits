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
    # défaut, ce qui ferait couper la matière pour rien — ajouter toute
    # nouvelle référence ici.
    "mistral-large-latest": 500_000,
    "mistral-medium-latest": 500_000,
    "mistral-small-latest": 500_000,
    "open-mistral-nemo": 500_000,
    "groq/compound": 8_000,
    "groq/compound-mini": 8_000,
    # ── Gemini, ajouté le 24/08 AVANT tout essai, et c'est le point ─────────
    # Sans ces entrées, un modèle Gemini retomberait sur les 12 000 par défaut :
    # la réservation d'écriture couperait les extraits jusqu'au plancher de 300
    # caractères, et le test A/B rendrait un verdict FAUX — on lirait « Gemini
    # écrit mal » là où on lui aurait donné cinq fois moins de matière qu'à
    # Mistral. Un banc d'essai truqué contre le candidat qu'il doit évaluer est
    # pire qu'un essai qu'on ne fait pas.
    #
    # ⚠ VALEUR RELAYÉE, NON VÉRIFIÉE À LA SOURCE. Le ~1 000 000 vient du relevé
    # du 18/08 consigné dans CLAUDE.md, pas d'une lecture de la documentation
    # Google. C'est exactement le type de chiffre qui a coûté le run du 17/08 :
    # `groq/compound` affichait 70 000 TPM dans une grille tarifaire et était en
    # réalité facturé sur le compteur d'un autre modèle à 8 000. Seul le corps
    # d'erreur de l'API fait foi — à confirmer au premier essai réel, et à
    # corriger ici si un 429 annonce autre chose.
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.0-flash-lite": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-1.5-pro": 1_000_000,
}
