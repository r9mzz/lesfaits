# -*- coding: utf-8 -*-
"""Classement éditorial au niveau du SUJET, pas seulement de l'article RSS.

Ce module ne baisse aucun seuil et ne rend aucun candidat supplémentaire
éligible. Il intervient uniquement APRÈS ``filtrer_et_classer`` : parmi les
candidats déjà admis, il regroupe les titres qui décrivent le même événement,
conserve un représentant par événement et favorise les faits couverts par
plusieurs rédactions indépendantes.

Objectif : éviter qu'une pièce magazine mono-source bien rédigée devance une
actualité du jour documentée simultanément par plusieurs médias.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict

STOP = {
    "dans", "pour", "avec", "sans", "plus", "moins", "leur", "leurs",
    "cette", "ces", "son", "ses", "une", "des", "les", "aux", "par",
    "sur", "que", "qui", "quoi", "dont", "mais", "donc", "cet", "est",
    "sont", "ete", "etre", "avoir", "apres", "avant", "entre", "chez",
    "vers", "contre", "selon", "comme", "tout", "tous", "toute",
    "toutes", "encore", "deja", "aussi", "faire", "fait", "faits", "peut",
    "peuvent", "annee", "annees", "france", "francais", "francaise",
}


def _stem_token(token: str) -> str:
    """Normalisation légère des flexions, volontairement conservatrice.

    Elle absorbe surtout les accords/pluriels fréquents dans les titres
    (``placée``/``place``, ``globes``/``globe``) sans transformer les mots en
    racines agressives. Le clustering exige toujours au moins deux mots communs.
    """
    if len(token) > 5 and token.endswith("ees"):
        return token[:-2]
    if len(token) > 5 and token.endswith("ee"):
        return token[:-1]
    if len(token) > 5 and token.endswith("es"):
        return token[:-1]
    if len(token) > 5 and token.endswith(("s", "x")):
        return token[:-1]
    return token


def _tokens(titre: str) -> set[str]:
    t = unicodedata.normalize("NFD", titre or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return {
        _stem_token(m) for m in re.findall(r"[a-z0-9]+", t)
        if len(m) >= 4 and m not in STOP
    }


def _source_name(item: dict) -> str:
    return str(
        item.get("source_name")
        or item.get("_source")
        or item.get("source")
        or "?"
    ).strip()


def _clusters(candidats: list[dict], seuil: float = 0.34) -> list[list[int]]:
    """Regroupe par similarité de titres pondérée IDF.

    Deux titres ne sont JAMAIS reliés sur un seul mot commun. L'IDF réduit le
    poids du vocabulaire omniprésent dans la collecte et conserve celui des
    termes distinctifs. Si tous les termes communs ont une IDF nulle (petit
    corpus composé de titres quasi identiques), on retombe sur un cosinus
    lexical non pondéré : cela évite un faux négatif mathématique sans autoriser
    les rapprochements sur un mot unique.

    Le seuil 0,34 est celui utilisé dans la mesure réelle du 10/08/2026 et doit
    être retesté sur plusieurs journées avant tout changement.
    """
    toks = [_tokens(i.get("title", "")) for i in candidats]
    df: Counter[str] = Counter()
    for s in toks:
        df.update(s)
    n = max(1, len(candidats))
    idf = {m: math.log(n / c) for m, c in df.items() if c}
    poids = [sum(idf.get(m, 0.0) for m in s) for s in toks]
    parent = list(range(len(candidats)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(candidats)):
        if not toks[a]:
            continue
        for b in range(a + 1, len(candidats)):
            if not toks[b]:
                continue
            communs = toks[a] & toks[b]
            if len(communs) < 2:
                continue
            numerateur = sum(idf.get(m, 0.0) for m in communs)
            if numerateur == 0.0:
                similarite = len(communs) / (
                    math.sqrt(len(toks[a]) * len(toks[b])) or 1.0
                )
            else:
                denominateur = math.sqrt(poids[a] * poids[b]) or 1.0
                similarite = numerateur / denominateur
            if similarite >= seuil:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

    groupes: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(candidats)):
        groupes[find(idx)].append(idx)
    return list(groupes.values())


def corroboration_bonus(nb_medias: int) -> int:
    """Bonus de classement uniquement ; ne change jamais le seuil d'éligibilité."""
    if nb_medias >= 5:
        return 36
    if nb_medias >= 3:
        return 24
    if nb_medias == 2:
        return 12
    return 0


def rank_subjects(candidats: list[dict], seuil_cluster: float = 0.34) -> list[dict]:
    """Retourne UN représentant par sujet, trié par intérêt journalistique.

    Le représentant est toujours l'article RSS du cluster qui avait déjà le
    meilleur score éditorial historique. Le bonus multi-source ne modifie pas
    ``_score`` : il est stocké séparément dans ``_selection_score`` afin de
    garder un diagnostic transparent et de ne jamais faire croire qu'un seuil
    de qualité a été franchi grâce au bonus.
    """
    if not candidats:
        return []

    ranked: list[dict] = []
    for groupe in _clusters(candidats, seuil_cluster):
        items = [candidats[i] for i in groupe]
        medias = {_source_name(i) for i in items if _source_name(i) != "?"}
        nb_medias = max(1, len(medias))
        representant = max(
            items,
            key=lambda i: (i.get("_score", -10_000), len(i.get("content", ""))),
        )
        out = dict(representant)
        bonus = corroboration_bonus(nb_medias)
        out["_corroboration_medias"] = nb_medias
        out["_corroboration_sources"] = sorted(medias)
        out["_selection_bonus"] = bonus
        out["_selection_score"] = out.get("_score", 0) + bonus
        ranked.append(out)

    return sorted(
        ranked,
        key=lambda i: (
            i.get("_selection_score", i.get("_score", 0)),
            i.get("_corroboration_medias", 1),
            i.get("_score", 0),
        ),
        reverse=True,
    )


def selectionner_sujets(
    candidats: list[dict],
    nb_max: int,
    quota_cat: int,
    quotas_par_categorie: dict[str, int],
) -> list[dict]:
    """Sélection finale par sujet, en conservant les quotas de catégorie."""
    selection: list[dict] = []
    compteur: dict[str, int] = {}
    for item in rank_subjects(candidats):
        if len(selection) >= nb_max:
            break
        cat = item.get("_cat", "societe")
        plafond = quotas_par_categorie.get(cat, quota_cat)
        if compteur.get(cat, 0) >= plafond:
            continue
        selection.append(item)
        compteur[cat] = compteur.get(cat, 0) + 1
    return selection
