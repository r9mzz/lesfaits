# -*- coding: utf-8 -*-
"""Compatibilité fournisseur pour le fact-checker.

Le cœur historique reste dans ``verification_legacy.py``. Ce module applique
uniquement la même résolution fournisseur/modèle que ``pipeline.py`` puis
expose le module historique comme ``verification``. Ainsi les fonctions du
fact-checker gardent leurs globals et les patches runtime V3 continuent de
modifier le vrai ``PROMPT_DETECTION``.

Sécurité de publication : une vérification indisponible ne doit jamais être
interprétée comme un feu vert. Le wrapper fournisseur transforme les états
``erreur_verification`` / ``non_verifie`` en rejet qualité, sans modifier les
seuils éditoriaux ni le contenu de l'article.
"""
from __future__ import annotations

import copy
import os
import re
import sys


import verification_legacy as _verification
from cles_fournisseur import cles_fournisseur
from modele_fournisseur import modele_redaction

_BASE_POUR_DEFAUT = os.getenv("LLM_BASE_URL", "")
_MODEL = modele_redaction()
_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
_LLM_KEYS = cles_fournisseur()
_LLM_KEY = _LLM_KEYS[0] if _LLM_KEYS else ""

_verification.GROQ_MODEL = _MODEL
if _LLM_KEYS:
    _verification.GROQ_KEYS = list(_LLM_KEYS)

if _BASE_URL:
    _verification.GROQ_URL = _BASE_URL.rstrip("/") + "/chat/completions"
else:
    _verification.GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_RETROSPECTIVE_SOURCE_RULE = """
⚠ CHRONOLOGIE DES SOURCES — une source publiée APRÈS un événement peut parfaitement le décrire rétrospectivement. La seule différence entre la date de publication de la source et la date de l'événement n'est JAMAIS, à elle seule, un motif ``annonce_perimee`` ou ``chronologie_confuse``. Signale ``annonce_perimee`` uniquement si le TEXTE DE L'ARTICLE présente comme futur, actuel ou définitif un état que les extraits fournis établissent explicitement comme déjà survenu, terminé, dépassé ou provisoire. Ne déduis jamais qu'une source « ne peut pas décrire » un événement antérieur simplement parce qu'elle a été publiée plus tard.
""".strip()
if _RETROSPECTIVE_SOURCE_RULE not in _verification.PROMPT_DETECTION:
    _verification.PROMPT_DETECTION += "\n\n" + _RETROSPECTIVE_SOURCE_RULE

_FUTURE_PROJECTION_RULE = """
⚠ PROJECTIONS ET FUTUR RÉEL — le simple emploi du futur, du conditionnel ou d'un verbe comme « prévoit », « projette », « envisage » n'est JAMAIS en soi un motif ``annonce_perimee``. Si les extraits décrivent réellement une prévision, un scénario, une échéance ou un événement encore futur à la date de l'article, l'article DOIT pouvoir le présenter comme futur. La date de publication d'une prévision antérieure à l'échéance confirme au contraire qu'il s'agit d'une projection ; elle ne la rend pas périmée. N'utilise ``annonce_perimee`` que lorsqu'un extrait plus récent établit explicitement que l'événement annoncé a déjà eu lieu, a été annulé, a changé d'état ou que la formulation temporelle de l'article contredit l'état le plus récent fourni. Ne transforme jamais une simple différence de temps grammatical en contradiction chronologique.
""".strip()
if _FUTURE_PROJECTION_RULE not in _verification.PROMPT_DETECTION:
    _verification.PROMPT_DETECTION += "\n\n" + _FUTURE_PROJECTION_RULE

_CURRENT_APPLICATION_RULE = """
⚠ ÉTAT EN VIGUEUR — dire qu'une réforme « est entrée en vigueur » à une date passée est parfaitement compatible avec une source plus récente qui la décrit comme « en vigueur », « applicable », « appliquée » ou « en cours d'application ». Cet état actuel confirme qu'elle a déjà pris effet ; il ne transforme pas l'entrée en vigueur passée en ``annonce_perimee``. Si la date exacte n'est pas confirmée par les extraits, traite ce point comme un éventuel défaut de preuve sur la date, jamais comme une contradiction chronologique. ``annonce_perimee`` ne s'applique que si un extrait plus récent établit que la réforme n'est finalement pas entrée en vigueur, a été reportée, annulée, remplacée ou a changé d'état.
""".strip()
if _CURRENT_APPLICATION_RULE not in _verification.PROMPT_DETECTION:
    _verification.PROMPT_DETECTION += "\n\n" + _CURRENT_APPLICATION_RULE

_AUTHORIZED_BIBLIOGRAPHY_RULE = """
⚠ SOURCE AUTORISÉE MAIS NON CITÉE — la présence d'une source dans le tableau ``sources`` sans renvoi [n] dans le corps n'est JAMAIS, à elle seule, une ``source_inventee``. ``source_inventee`` signifie qu'un média, une institution, une étude ou une attribution UTILISÉE DANS LE TEXTE n'appartient pas à la liste autorisée, ou qu'un renvoi [n] attribue un fait que la source correspondante ne confirme pas. Une entrée bibliographique autorisée mais finalement inutilisée peut être superflue, mais elle n'est pas inventée et ne doit pas bloquer la publication sous ce motif.
""".strip()
if _AUTHORIZED_BIBLIOGRAPHY_RULE not in _verification.PROMPT_DETECTION:
    _verification.PROMPT_DETECTION += "\n\n" + _AUTHORIZED_BIBLIOGRAPHY_RULE

_verification._provider_original_llm_call = _verification._llm_call
_PROVIDER_FATAL_ERROR = None
_REQUESTS_MODULE = getattr(_verification, "requests", None)
_TRANSIENT_REQUEST_ERRORS = tuple(
    cls
    for cls in (
        getattr(_REQUESTS_MODULE, "Timeout", None),
        getattr(_REQUESTS_MODULE, "ConnectionError", None),
    )
    if isinstance(cls, type)
)


def _provider_name() -> str:
    base = _BASE_URL.lower()
    if "mistral" in base:
        return "Mistral"
    if base:
        return "Fournisseur LLM"
    return "Groq"


def _normaliser_erreur_fournisseur(message: str) -> str:
    if _BASE_URL and message.startswith("Groq "):
        return _provider_name() + message[len("Groq"):]
    return message


def _provider_auth_rotating_llm_call(*args, **kwargs):
    global _PROVIDER_FATAL_ERROR
    if _PROVIDER_FATAL_ERROR is not None:
        raise RuntimeError(_PROVIDER_FATAL_ERROR)
    retry_transitoire_utilise = False
    while True:
        try:
            return _verification._provider_original_llm_call(*args, **kwargs)
        except _TRANSIENT_REQUEST_ERRORS as exc:
            if retry_transitoire_utilise:
                raise
            retry_transitoire_utilise = True
            print(f"     [VERIF] panne réseau transitoire ({type(exc).__name__}) — une relance")
            continue
        except RuntimeError as exc:
            message = str(exc)
            if re.match(r"Groq 5\d\d:", message):
                if retry_transitoire_utilise:
                    raise
                retry_transitoire_utilise = True
                libelle = _normaliser_erreur_fournisseur(message).split(":", 1)[0]
                print(f"     [VERIF] erreur fournisseur transitoire ({libelle}) — une relance")
                continue
            if message.startswith("Groq 402:"):
                _PROVIDER_FATAL_ERROR = _normaliser_erreur_fournisseur(message)
                print("     [VERIF] fournisseur indisponible de façon permanente pour ce processus (HTTP 402) — appels suivants bloqués")
                raise RuntimeError(_PROVIDER_FATAL_ERROR) from exc
            if not (message.startswith("Groq 401:") or message.startswith("Groq 403:")):
                raise
            mortes = getattr(_verification, "_CLES_MORTES_JOUR", set())
            vivantes = [k for k in _verification.GROQ_KEYS if k not in mortes]
            if not vivantes:
                raise
            cle_invalide = vivantes[0]
            _verification.GROQ_KEYS = [k for k in _verification.GROQ_KEYS if k != cle_invalide]
            print("     [VERIF] clé refusée par authentification (401/403) — retirée de la rotation pour ce processus")
            if not _verification.GROQ_KEYS:
                raise RuntimeError("Aucune clé de vérification valide après erreur d'authentification") from exc


_verification._llm_call = _provider_auth_rotating_llm_call

_verification._provider_original_corriger = _verification.corriger


def _provider_sources_immutables_corriger(art: dict, *args, **kwargs):
    sources_originales = copy.deepcopy(art.get("sources", [])) if isinstance(art, dict) else []
    corrige = _verification._provider_original_corriger(art, *args, **kwargs)
    if isinstance(corrige, dict):
        corrige["sources"] = sources_originales
    return corrige


_verification.corriger = _provider_sources_immutables_corriger


def _provider_source_inventee_bibliographie_autorisee(probleme: dict, art: dict) -> bool:
    if str(probleme.get("type") or "") != "source_inventee" or not isinstance(art, dict):
        return False
    texte = " ".join(str(probleme.get(k) or "") for k in ("phrase", "description"))
    if not texte:
        return False
    for source in art.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if url and url in texte:
            print("     [JUGE] source_inventee écarté — le reproche vise une entrée bibliographique dont l'URL figure déjà dans les sources autorisées")
            return True
    return False


_verification._provider_original_detecter = _verification.detecter


def _provider_detecter(art: dict, *args, **kwargs):
    rapport = _verification._provider_original_detecter(art, *args, **kwargs)
    if not isinstance(rapport, dict):
        return rapport
    problemes = rapport.get("problemes")
    if not isinstance(problemes, list):
        return rapport
    filtres = [p for p in problemes if not _provider_source_inventee_bibliographie_autorisee(p, art)]
    if len(filtres) == len(problemes):
        return rapport
    rapport = copy.deepcopy(rapport)
    rapport["problemes"] = filtres
    if not filtres and not rapport.get("sujet_sensible") and not rapport.get("angle_insuffisant"):
        rapport["conforme"] = True
    return rapport


_verification._provider_source_inventee_bibliographie_autorisee = _provider_source_inventee_bibliographie_autorisee
_verification.detecter = _provider_detecter

_SOURCE_ABSENCE_RE = re.compile(r"(?:la\s+)?source\s*\[?\d+\]?[^.]{0,180}(?:ne\s+(?:pr[ée]cise|mentionne|d[ée]taille|fournit|donne|indique)\s+pas|n['’](?:indique|apporte)\s+pas)", re.IGNORECASE)
_ARTICLE_OMISSION_RE = re.compile(r"(?:l['’]article|la\s+phrase)[^.]{0,220}(?:ne\s+(?:pr[ée]cise|mentionne|int[èe]gre|d[ée]taille|fournit|donne)\s+pas|omet)", re.IGNORECASE)
_PREUVE_RENFORCEE_RE = re.compile(r"efficacit[ée]|survie|comparateur|phase\s*[123]|pr[ée]clinique|comme\s+(?:un\s+)?(?:fait|r[ée]sultat)\s+(?:acquis|[ée]tabli)|pr[ée]sente[^.]{0,80}(?:comme\s+[ée]tabli|comme\s+acquis)", re.IGNORECASE)
_RESERVE_DEJA_PRESENTE_RE = re.compile(r"d[ée]j[àa]\s+(?:mentionn[ée]e?s?|pr[ée]cis[ée]e?s?|indiqu[ée]e?s?|pr[ée]sent[ée]e?s?|int[ée]gr[ée]e?s?)[^.]{0,140}(?:faits|nuances|article|autre\s+section)", re.IGNORECASE)
_DEMANDE_REPETITION_RESUME_RE = re.compile(r"(?:le\s+)?r[ée]sum[ée][^.]{0,100}\bdoit\b[^.]{0,100}(?:rappeler|reprendre|mentionner|r[ée]p[ée]ter)", re.IGNORECASE)
_RESERVE_RESUME_CORRECTE_RE = re.compile(r"(?:formulation\s+du\s+)?r[ée]sum[ée][^.]{0,140}(?:reprend|int[èe]gre|mentionne)[^.]{0,80}(?:correctement|d[ée]j[àa])[^.]{0,120}(?:r[ée]serve|nuance|limite)", re.IGNORECASE)
_TITRE_DONNEES_MENACEES_RE = re.compile(r"titre[^.]{0,120}[«\"']?[^.]{0,80}\bdonn[ée]es?\s+menac[ée]es?\b", re.IGNORECASE)
_PHRASE_COMPROMISSION_PRUDENTE_RE = re.compile(r"\b(?:pourrait|pourraient|aurait|auraient)\b[^.]{0,100}\bcompromis(?:e|es)?\b[^.]{0,120}\bsans\b[^.]{0,80}\bpreuve\b", re.IGNORECASE)
_ANNONCE_INTENTION_RE = re.compile(r"\b(?:a|ont)\s+annonc[ée](?:e|es|s)?\s+(?:qu['’]?[a-zà-ÿ]+\s+)?(?:vouloir|envisager|projeter|prévoir)\b", re.IGNORECASE)
_DESCRIPTION_INTENTION_RE = re.compile(r"\b(?:intention|projet|envisag[ée]|vouloir|conditionnel|pas\s+(?:encore\s+)?acquis|non\s+acquis)\b", re.IGNORECASE)
_DESCRIPTION_PERIMEE_RE = re.compile(r"\b(?:déjà\s+(?:eu\s+lieu|survenu|réalis[ée]|termin[ée])|annul[ée]|abandonn[ée]|remplac[ée]|n['’]est\s+plus|a\s+déjà\s+eu\s+lieu)\b", re.IGNORECASE)
_ENTREE_EN_VIGUEUR_RE = re.compile(r"\b(?:est\s+)?entr[ée]e?\s+en\s+vigueur\b", re.IGNORECASE)
_APPLICATION_ACTUELLE_RE = re.compile(r"\b(?:en\s+cours\s+d['’]application|actuellement\s+applicable|toujours\s+en\s+vigueur|est\s+applicable|est\s+appliqu[ée]e?)\b", re.IGNORECASE)
_ECHEANCE_FUTURE_RE = re.compile(r"\b(?:à\s+compter\s+du|à\s+partir\s+du)\s+\d{1,2}(?:er)?\s+[a-zà-ÿ]+\s+20\d{2}\b", re.IGNORECASE)
_VERBE_FUTUR_RE = re.compile(r"\b(?:devra|devront|sera|seront|entrera|entreront|s['’]appliquera|s['’]appliqueront)\b", re.IGNORECASE)
_DESCRIPTION_PAS_ENCORE_RE = re.compile(r"\b(?:n['’]est\s+pas\s+encore|ne\s+sont\s+pas\s+encore|pas\s+encore)\b[^.]{0,80}\b(?:en\s+vigueur|effective?s?|applicable?s?|appliqu[ée]e?s?)\b", re.IGNORECASE)
_DESCRIPTION_ECHEANCE_CONTREDITE_RE = re.compile(r"\b(?:report[ée]e?s?|repouss[ée]e?s?|d[ée]cal[ée]e?s?|annul[ée]e?s?|abandonn[ée]e?s?|remplac[ée]e?s?)\b|(?:aucune|pas\s+de)\s+source[^.]{0,80}(?:confirme|[ée]tablit)[^.]{0,40}\bdate\b", re.IGNORECASE)
_DATE_FR_RE = re.compile(r"\b\d{1,2}(?:er)?\s+[a-zà-ÿ]+\s+20\d{2}\b", re.IGNORECASE)
_APPROBATION_COMMISSION_RE = re.compile(r"\bcommission\s+europ[ée]enne\s+a\s+approuv[ée]\b", re.IGNORECASE)
_COMMUNIQUE_COMMISSION_RE = re.compile(r"\bcommuniqu[ée]\s+(?:officiel\s+)?(?:de\s+)?(?:la\s+)?commission\b", re.IGNORECASE)
_DESCRIPTION_DECISION_CONTREDITE_RE = re.compile(r"\b(?:annul[ée]e?|retir[ée]e?|r[ée]voqu[ée]e?|report[ée]e?|repouss[ée]e?|remplac[ée]e?|provisoire|proposition|non\s+d[ée]finitive?|pas\s+d[ée]finitive?|sous\s+r[ée]serve)\b", re.IGNORECASE)
_ATTRIBUTION_ACTIVE_RE = re.compile(
    r"\b(?:plusieurs|certains?|des)\s+[a-zà-ÿ][^,.;:]{0,60}\s+(?:a|ont)\s+(?:qualifi[ée]e?s?|jug[ée]e?s?|estim[ée]e?s?|affirm[ée]e?s?|d[ée]clar[ée]e?s?)\b",
    re.IGNORECASE,
)
_ATTRIBUTION_PASSIVE_RE = re.compile(
    r"\b(?:est|sont)\s+(?:jug[ée]e?s?|qualifi[ée]e?s?|estim[ée]e?s?)\s+[^,.;:]{0,100}\bpar\s+(?:certains?|plusieurs|des)\s+[a-zà-ÿ]",
    re.IGNORECASE,
)


def _provider_reproche_exige_source_absente(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "niveau_preuve_insuffisant":
        return False
    description = str(probleme.get("description") or "")
    if not (_SOURCE_ABSENCE_RE.search(description) and _ARTICLE_OMISSION_RE.search(description)):
        return False
    if _PREUVE_RENFORCEE_RE.search(description):
        return False
    print("     [JUGE] reproche écarté — le rapport exige une limite qu'il déclare lui-même absente de la source (règle de symétrie)")
    return True


def _provider_reproche_exige_repetition(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "niveau_preuve_insuffisant":
        return False
    description = str(probleme.get("description") or "")
    if _RESERVE_DEJA_PRESENTE_RE.search(description) and _DEMANDE_REPETITION_RESUME_RE.search(description):
        print("     [JUGE] reproche écarté — le rapport reconnaît la réserve déjà présente puis exige sa répétition dans le résumé")
        return True
    phrase = str(probleme.get("phrase") or "")
    if (_RESERVE_RESUME_CORRECTE_RE.search(description)
            and _TITRE_DONNEES_MENACEES_RE.search(description)
            and _PHRASE_COMPROMISSION_PRUDENTE_RE.search(phrase)):
        print("     [JUGE] reproche écarté — le résumé et la phrase portent déjà la réserve, tandis que le titre dit seulement que les données sont menacées")
        return True
    return False


def _provider_annonce_intention_pas_perimee(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "annonce_perimee":
        return False
    phrase = str(probleme.get("phrase") or "")
    description = str(probleme.get("description") or "")
    if not (_ANNONCE_INTENTION_RE.search(phrase) and _DESCRIPTION_INTENTION_RE.search(description)):
        return False
    if _DESCRIPTION_PERIMEE_RE.search(description):
        return False
    print("     [JUGE] reproche écarté — « a annoncé vouloir/envisager » décrit une annonce passée d'un projet futur, pas une annonce périmée")
    return True


def _provider_entree_en_vigueur_pas_perimee(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "annonce_perimee":
        return False
    phrase = str(probleme.get("phrase") or "")
    description = str(probleme.get("description") or "")
    if not (_ENTREE_EN_VIGUEUR_RE.search(phrase) and _APPLICATION_ACTUELLE_RE.search(description)):
        return False
    if _DESCRIPTION_PERIMEE_RE.search(description):
        return False
    if re.search(r"\b(?:date|1er\s+janvier|ne\s+confirme\s+pas|pas\s+explicitement)\b", description, re.IGNORECASE):
        return False
    print("     [JUGE] annonce_perimee écarté — une réforme actuellement appliquée peut être entrée en vigueur à une date passée")
    return True


def _provider_echeance_future_pas_perimee(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "annonce_perimee":
        return False
    phrase = str(probleme.get("phrase") or "")
    description = str(probleme.get("description") or "")
    if not (_ECHEANCE_FUTURE_RE.search(phrase) and _VERBE_FUTUR_RE.search(phrase) and _DESCRIPTION_PAS_ENCORE_RE.search(description)):
        return False
    if _DESCRIPTION_PERIMEE_RE.search(description) or _DESCRIPTION_ECHEANCE_CONTREDITE_RE.search(description):
        return False
    print("     [JUGE] annonce_perimee écarté — le rapport reproche à une échéance explicitement future de ne pas être encore en vigueur")
    return True


def _provider_approbation_commission_meme_jour_pas_perimee(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "annonce_perimee":
        return False
    phrase = str(probleme.get("phrase") or "")
    description = str(probleme.get("description") or "")
    if not (_APPROBATION_COMMISSION_RE.search(phrase) and _COMMUNIQUE_COMMISSION_RE.search(description)):
        return False
    dates_phrase = {m.group(0).lower() for m in _DATE_FR_RE.finditer(phrase)}
    dates_description = {m.group(0).lower() for m in _DATE_FR_RE.finditer(description)}
    if not dates_phrase.intersection(dates_description):
        return False
    if _DESCRIPTION_DECISION_CONTREDITE_RE.search(description):
        return False
    print("     [JUGE] annonce_perimee écarté — le communiqué primaire de la Commission daté du jour même établit l'approbation comme fait accompli")
    return True


def _provider_accusation_opinion_explicitement_attribuee(probleme: dict) -> bool:
    """Écarte uniquement un reproche d'accusation quand la phrase attribue déjà
    explicitement le jugement à un groupe identifié.

    Les deux formes observées sont couvertes : sujet + verbe d'opinion
    ("plusieurs patrons ont qualifié") et passif avec agent explicite
    ("est jugée risquée par certains économistes"). Une accusation directe ou
    un jugement sans auteur identifié reste bloquant.
    """
    if str(probleme.get("type") or "") != "accusation_presentee_comme_fait":
        return False
    phrase = str(probleme.get("phrase") or "")
    if not phrase:
        return False
    if not (_ATTRIBUTION_ACTIVE_RE.search(phrase) or _ATTRIBUTION_PASSIVE_RE.search(phrase)):
        return False
    print("     [JUGE] accusation_presentee_comme_fait écarté — le jugement est déjà explicitement attribué dans la phrase")
    return True


_verification._reproche_exige_source_absente = _provider_reproche_exige_source_absente
_verification._reproche_exige_repetition = _provider_reproche_exige_repetition
_verification._annonce_intention_pas_perimee = _provider_annonce_intention_pas_perimee
_verification._entree_en_vigueur_pas_perimee = _provider_entree_en_vigueur_pas_perimee
_verification._echeance_future_pas_perimee = _provider_echeance_future_pas_perimee
_verification._approbation_commission_meme_jour_pas_perimee = _provider_approbation_commission_meme_jour_pas_perimee
_verification._accusation_opinion_explicitement_attribuee = _provider_accusation_opinion_explicitement_attribuee
if hasattr(_verification, "_problemes_bloquants"):
    _verification._provider_original_problemes_bloquants = _verification._problemes_bloquants

    def _provider_problemes_bloquants(problemes: list, article: dict | None = None) -> list:
        retenus = _verification._provider_original_problemes_bloquants(problemes, article)
        return [
            p for p in retenus
            if not _provider_reproche_exige_source_absente(p)
            and not _provider_reproche_exige_repetition(p)
            and not _provider_annonce_intention_pas_perimee(p)
            and not _provider_entree_en_vigueur_pas_perimee(p)
            and not _provider_echeance_future_pas_perimee(p)
            and not _provider_approbation_commission_meme_jour_pas_perimee(p)
            and not _provider_accusation_opinion_explicitement_attribuee(p)
        ]

    _verification._problemes_bloquants = _provider_problemes_bloquants

_verification._provider_original_verifier_article = _verification.verifier_article


def _provider_fail_closed_verifier_article(*args, **kwargs):
    article, statut = _verification._provider_original_verifier_article(*args, **kwargs)
    if statut in {"erreur_verification", "non_verifie"}:
        slug = article.get("slug", "?") if isinstance(article, dict) else "?"
        print(f"     [REJET QUALITÉ] vérification indisponible ({statut}) — publication automatique interdite")
        try:
            _verification._log(slug, "rejete_qualite", {"raison": "verification_indisponible", "statut_verification_initial": statut})
        except Exception:
            pass
        return article, "rejete_qualite"
    return article, statut


_verification.verifier_article = _provider_fail_closed_verifier_article


def _empreinte(k: str) -> str:
    return f"{k[:4]}…{k[-3:]} ({len(k)} car.)" if len(k) > 8 else "(vide ou trop courte)"


print(
    f"     [VERIF-AUTH] cible={_verification.GROQ_URL} · modèle={_MODEL} · clés={len(_verification.GROQ_KEYS)} · source={'LLM_API_KEY' if _LLM_KEY else 'GROQ_API_KEY*'} · {_empreinte(_verification.GROQ_KEYS[0]) if _verification.GROQ_KEYS else 'AUCUNE'}",
    file=sys.stderr,
    flush=True,
)

sys.modules[__name__] = _verification
