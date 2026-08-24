# -*- coding: utf-8 -*-
"""Résolution des clés du fournisseur LLM, partagée génération / vérification.

⚠ POURQUOI CE MODULE EXISTE — l'hypothèse du 18/08 a été démentie le 22/08.

En branchant Mistral, on avait écrit : « un fournisseur dont le palier gratuit
accorde 1 milliard de tokens par mois n'a pas ce problème : une clé suffit, et
en ouvrir onze n'apporterait rien. » Le run du 22/08 a épuisé le quota AUX
TROIS QUARTS (402 « Check your subscription » à la ligne 892 sur 1234), puis
les runs des 23 et 24 n'ont produit aucune ligne — 73 refus, zéro article, et
un job GitHub vert à chaque fois.

La leçon est celle déjà écrite pour Groq le 10/08 : le nombre de clés n'est pas
une propriété du fournisseur, c'est une variable d'exploitation. On lit donc
`LLM_API_KEY`, `LLM_API_KEY_2`, `LLM_API_KEY_3`, … sans plafond codé en dur —
exactement le mécanisme de `GROQ_API_KEY_2..N`, pour ne pas avoir à toucher au
code le jour où une clé de plus est ajoutée.

Une seule fonction, lue par `pipeline.py` ET par `verification.py` : la panne
du 19/08 (401 sur le fact-check) venait précisément de deux résolutions de clés
divergentes entre les deux côtés. Ce module existe pour que ça ne puisse plus
arriver.
"""
from __future__ import annotations

import os

# Borne haute du balayage. Ce n'est PAS un plafond de clés utilisables : c'est
# la borne d'une boucle qui s'arrête au premier trou. La même valeur que côté
# Groq, pour que les deux mécanismes se lisent pareil.
_MAX_INDEX = 40


def cles_fournisseur(env: dict | None = None) -> list[str]:
    """Rend les clés du fournisseur unique, dans l'ordre, sans doublon.

    Vide si `LLM_API_KEY` n'est pas définie : le fournisseur historique (Groq
    et sa rotation propre) reste alors seul maître, comportement inchangé.
    """
    lire = (env or os.environ).get

    # ⚠ LLM_API_KEY est la clé de VOÛTE, pas la première d'une liste. Sans
    # elle, on ne renvoie rien même si des clés secondaires existent : basculer
    # sur un fournisseur à moitié configuré est pire qu'une panne franche —
    # c'est le 401 silencieux du 19/08, où la génération et le fact-check
    # regardaient deux fournisseurs différents sans que rien ne le dise.
    principale = (lire("LLM_API_KEY", "") or "").strip()
    if not principale:
        return []

    brutes = [principale]
    brutes += [lire(f"LLM_API_KEY_{i}", "") or "" for i in range(2, _MAX_INDEX + 1)]

    vues: set[str] = set()
    cles: list[str] = []
    for k in brutes:
        k = k.strip()
        # Le dédoublonnage n'est pas cosmétique : deux secrets pointant sur la
        # même clé feraient croire à deux quotas là où il n'y en a qu'un, et la
        # rotation tournerait sur une clé déjà morte en la comptant deux fois.
        if k and k not in vues:
            vues.add(k)
            cles.append(k)
    return cles
