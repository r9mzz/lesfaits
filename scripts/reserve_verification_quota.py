# -*- coding: utf-8 -*-
"""Réserve quelques clés Groq au fact-check sans réduire la qualité.

Le rédacteur et le vérificateur utilisaient exactement la même rotation. Sur un
run long, la génération pouvait donc vider toutes les clés avant la passe de
vérification : un bon article était alors rejeté pour protocole incomplet.

Ce contexte importe d'abord ``verification`` avec toutes les clés, place les
clés réservées en tête de sa rotation, puis les masque temporairement de
l'environnement pendant le chargement de ``pipeline.py``. Le rédacteur ne peut
pas les consommer ; le fact-check peut ensuite retomber sur les autres clés si
les réservées sont indisponibles.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from types import ModuleType
from typing import Iterator

DEFAULT_RESERVED = 2
MIN_WRITER_KEYS = 3
MAX_RESERVED = 5


def _key_entries() -> list[tuple[str, str]]:
    names = ["GROQ_API_KEY", *[f"GROQ_API_KEY_{i}" for i in range(2, 41)]]
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        value = os.getenv(name, "").strip()
        if not value or value in seen:
            continue
        entries.append((name, value))
        seen.add(value)
    return entries


def _configured_count(value: int | None = None) -> int:
    if value is None:
        raw = os.getenv("GROQ_RESERVED_CHECK_KEYS", str(DEFAULT_RESERVED))
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("GROQ_RESERVED_CHECK_KEYS doit être un entier") from exc
    if not 0 <= value <= MAX_RESERVED:
        raise ValueError(
            f"GROQ_RESERVED_CHECK_KEYS doit rester compris entre 0 et {MAX_RESERVED}"
        )
    return value


@contextmanager
def reserved_verification_quota(
    reserve_count: int | None = None,
    verification_module: ModuleType | None = None,
) -> Iterator[dict[str, object]]:
    """Masque temporairement les clés réservées au pipeline de rédaction."""
    reserve_count = _configured_count(reserve_count)
    entries = _key_entries()
    if reserve_count == 0 or len(entries) < MIN_WRITER_KEYS + reserve_count:
        yield {
            "enabled": False,
            "reserved": 0,
            "writer_keys": len(entries),
        }
        return

    reserved_entries = entries[-reserve_count:]
    reserved_values = [value for _, value in reserved_entries]
    writer_values = [value for _, value in entries[:-reserve_count]]

    if verification_module is None:
        import verification as verification_module  # type: ignore[no-redef]

    # Le fact-check commence par les clés protégées, puis conserve toutes les
    # autres en repli. Aucune capacité totale n'est supprimée du vérificateur.
    verification_module.GROQ_KEYS = reserved_values + writer_values

    reserved_set = set(reserved_values)
    removed: dict[str, str] = {}
    for name in ["GROQ_API_KEY", *[f"GROQ_API_KEY_{i}" for i in range(2, 41)]]:
        value = os.getenv(name, "")
        if value in reserved_set:
            removed[name] = value
            os.environ.pop(name, None)

    print(
        f"[PRÉVOL] Quota Groq : {len(writer_values)} clé(s) rédaction, "
        f"{len(reserved_values)} clé(s) réservée(s) au fact-check"
    )
    try:
        yield {
            "enabled": True,
            "reserved": len(reserved_values),
            "writer_keys": len(writer_values),
            "reserved_values": tuple(reserved_values),
        }
    finally:
        os.environ.update(removed)
