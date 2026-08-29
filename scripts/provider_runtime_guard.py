"""Validation minimale de la configuration du fournisseur LLM.

Le runtime ne doit jamais mélanger les identifiants Groq et ceux d'un
fournisseur externe. ``LLM_BASE_URL`` et ``LLM_API_KEY`` forment donc une
configuration atomique : soit les deux sont absents (Groq par défaut), soit
les deux sont présents.

Le runner V3 historique résout encore son fallback Groq avant d'appeler ce
prévol. Quand une base Mistral est configurée sans override explicite utile,
il peut donc arriver ici avec ``openai/gpt-oss-120b`` déjà injecté. Ce nom
n'existe pas chez Mistral : on le remplace par le défaut Mistral canonique
avant tout import du pipeline. Un override Mistral explicite est conservé.

Depuis le run #297 (29/08), le prévol vérifie aussi qu'au moins une clé du
fournisseur externe peut réellement appeler le modèle configuré. Les erreurs
401/402/403/404 sont permanentes pour le couple clé/modèle : si TOUTES les clés
échouent ainsi, continuer la collecte et tenter des dizaines de sujets ne peut
rien produire. Les erreurs transitoires (429, 5xx, réseau) restent au contraire
à la charge des mécanismes de retry du pipeline et ne bloquent pas le run ici.
"""
from __future__ import annotations

import os
import re


_GROQ_RUNTIME_DEFAULT = "openai/gpt-oss-120b"
_MISTRAL_RUNTIME_DEFAULT = "mistral-large-latest"
_PERMANENT_PROVIDER_STATUS = {401, 402, 403, 404}


def _provider_keys(values) -> list[str]:
    """Retourne les clés LLM dédiées, dans l'ordre, sans doublons ni blancs."""
    found: list[tuple[int, str]] = []
    for name, raw in values.items():
        if name == "LLM_API_KEY":
            rank = 1
        else:
            match = re.fullmatch(r"LLM_API_KEY_(\d+)", str(name))
            if not match:
                continue
            rank = int(match.group(1))
        key = str(raw or "").strip()
        if key:
            found.append((rank, key))
    found.sort(key=lambda item: item[0])
    result: list[str] = []
    for _, key in found:
        if key not in result:
            result.append(key)
    return result


def validate_provider_access(values=None, post=None) -> None:
    """Échoue tôt si toutes les clés ont une panne d'accès permanente.

    Ce contrôle est volontairement étroit : 401/402/403/404 seulement. Un 429,
    un 5xx ou une exception réseau peut disparaître quelques secondes plus tard
    et ne doit donc jamais transformer un incident transitoire en panne globale.
    ``post`` est injectable afin que la régression soit 100 % déterministe et
    ne consomme aucune API.
    """
    values = os.environ if values is None else values
    base_url = str(values.get("LLM_BASE_URL", "") or "").strip()
    if not base_url:
        return
    model = str(values.get("GROQ_MODEL_OVERRIDE", "") or "").strip()
    keys = _provider_keys(values)
    if not model or not keys:
        return  # validate_provider_env porte le contrat de présence des variables.

    if post is None:
        import requests
        post = requests.post

    endpoint = base_url.rstrip("/") + "/chat/completions"
    permanent_failures: list[tuple[int, str]] = []
    transient_seen = False
    for key in keys:
        try:
            response = post(
                endpoint,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Réponds uniquement OK."}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
                timeout=20,
            )
        except Exception as exc:
            transient_seen = True
            print(f"[PRÉVOL FOURNISSEUR] sonde réseau transitoirement indisponible : {type(exc).__name__}")
            continue

        status = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status < 400:
            print(f"[PRÉVOL FOURNISSEUR] accès modèle confirmé : {model}")
            return
        if status in _PERMANENT_PROVIDER_STATUS:
            body = str(getattr(response, "text", "") or "").replace("\n", " ")[:240]
            permanent_failures.append((status, body))
            continue
        # 429, 5xx et statuts inconnus : laisser le pipeline appliquer ses
        # retries/rotations plutôt que conclure trop tôt à une panne permanente.
        transient_seen = True

    if permanent_failures and len(permanent_failures) == len(keys) and not transient_seen:
        statuses = ", ".join(str(status) for status, _ in permanent_failures)
        details = " | ".join(body for _, body in permanent_failures if body)[:500]
        suffix = f" — {details}" if details else ""
        raise RuntimeError(
            f"Accès fournisseur impossible avant génération : modèle {model}, "
            f"toutes les clés refusées par erreur permanente ({statuses}){suffix}. "
            "Arrêt avant collecte pour éviter de retenter chaque sujet avec une configuration inutilisable."
        )


def validate_provider_env(env: dict[str, str] | None = None) -> None:
    """Refuse une configuration partielle et aligne le fallback au fournisseur."""
    values = os.environ if env is None else env
    base_url = str(values.get("LLM_BASE_URL", "") or "").strip()
    api_key = str(values.get("LLM_API_KEY", "") or "").strip()
    if bool(base_url) != bool(api_key):
        if base_url:
            detail = "LLM_BASE_URL est défini mais LLM_API_KEY est vide"
        else:
            detail = "LLM_API_KEY est défini mais LLM_BASE_URL est vide"
        raise RuntimeError(
            "Configuration fournisseur incomplète : " + detail
            + ". Les deux variables doivent être définies ensemble ou laissées vides. "
            "Refus avant tout appel réseau."
        )

    if base_url and "mistral.ai" in base_url.lower():
        model = str(values.get("GROQ_MODEL_OVERRIDE", "") or "").strip()
        if not model or model == _GROQ_RUNTIME_DEFAULT:
            values["GROQ_MODEL_OVERRIDE"] = _MISTRAL_RUNTIME_DEFAULT

    # Le runner de production appelle sans ``env`` : c'est le seul chemin où
    # l'on effectue une sonde réelle. Les tests de résolution de modèle lancent
    # volontairement le runner avec de fausses clés ; ils posent donc le garde
    # explicite ci-dessous. Cette variable n'est pas câblée dans pipeline.yml :
    # la production sonde toujours réellement le fournisseur.
    skip_probe = str(values.get("LLM_SKIP_ACCESS_PROBE", "") or "").strip() == "1"
    if env is None and base_url and not skip_probe:
        validate_provider_access(values)
