# -*- coding: utf-8 -*-
"""Classement éditorial au niveau du SUJET, pas seulement de l'article RSS.

Ce module ne baisse aucun seuil et ne rend aucun candidat supplémentaire
éligible. Il intervient uniquement APRÈS ``filtrer_et_classer`` : parmi les
candidats déjà admis, il regroupe les titres qui décrivent le même événement,
conserve un représentant par événement et favorise les faits couverts par
plusieurs rédactions indépendantes.

Objectif : éviter qu'une pièce magazine mono-source bien rédigée devance une
actualité du jour documentée simultanément par plusieurs médias, et éviter de
repayer plusieurs runs de suite pour exactement le même sujet déjà rejeté.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

STOP = {
    "dans", "pour", "avec", "sans", "plus", "moins", "leur", "leurs",
    "cette", "ces", "son", "ses", "une", "des", "les", "aux", "par",
    "sur", "que", "qui", "quoi", "dont", "mais", "donc", "cet", "est",
    "sont", "ete", "etre", "avoir", "apres", "avant", "entre", "chez",
    "vers", "contre", "selon", "comme", "tout", "tous", "toute",
    "toutes", "encore", "deja", "aussi", "faire", "fait", "faits", "peut",
    "peuvent", "annee", "annees", "france", "francais", "francaise",
}

ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_LOG = ROOT / "data" / "verification_log.json"
REJECT_COOLDOWN_HOURS = 36


def _stem_token(token: str) -> str:
    """Normalisation légère des flexions, volontairement conservatrice."""
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


def _slugify_title(titre: str) -> str:
    """Normalisation stricte titre→slug, utilisée uniquement pour le cooldown.

    On exige une égalité exacte avec le slug rejeté : pas de similarité floue,
    afin qu'une nouvelle actualité voisine ne soit jamais écartée par erreur.
    """
    t = unicodedata.normalize("NFD", titre or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:100]


def _recent_rejected_slugs(
    log_path: Path = VERIFICATION_LOG,
    now: datetime | None = None,
    cooldown_hours: int = REJECT_COOLDOWN_HOURS,
) -> set[str]:
    """Slugs rejetés récemment pour qualité ou sensibilité.

    Le mécanisme est volontairement conservateur : seulement des rejets
    explicites, seulement sur une fenêtre courte, et uniquement une égalité
    exacte avec le titre normalisé du candidat courant.
    """
    if not log_path.exists():
        return set()
    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(entries, list):
        return set()

    now = now or datetime.now()
    cutoff = now - timedelta(hours=cooldown_hours)
    out: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("statut") not in {"rejete_qualite", "rejete_sensible"}:
            continue
        slug = str(entry.get("slug") or "").strip()
        raw_date = str(entry.get("date") or "").strip()
        if not slug or not raw_date:
            continue
        try:
            when = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if when.tzinfo is not None:
                when = when.replace(tzinfo=None)
        except ValueError:
            continue
        if when >= cutoff:
            out.add(slug)
    return out


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


def rank_subjects(
    candidats: list[dict],
    seuil_cluster: float = 0.34,
    rejected_slugs: set[str] | None = None,
) -> list[dict]:
    """Retourne UN représentant par sujet, trié par intérêt journalistique.

    Les sujets rejetés très récemment sont exclus uniquement si leur slug est
    exactement celui obtenu à partir du titre courant. Ce cooldown économise le
    quota sans élargir ni assouplir aucun critère éditorial.
    """
    if not candidats:
        return []

    rejected_slugs = _recent_rejected_slugs() if rejected_slugs is None else rejected_slugs
    admissibles = [
        item for item in candidats
        if _slugify_title(item.get("title", "")) not in rejected_slugs
    ]
    if not admissibles:
        return []

    ranked: list[dict] = []
    for groupe in _clusters(admissibles, seuil_cluster):
        items = [admissibles[i] for i in groupe]
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
