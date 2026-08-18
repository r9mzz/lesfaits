# -*- coding: utf-8 -*-
"""Profondeur et progression éditoriales des articles longs.

Ce module intervient après le garde factuel de ``editorial_quality.py`` :
- chaque section doit apporter de la matière nouvelle ;
- les sources qui semblent toutes reprendre le même titre sont signalées ;
- des intertitres informatifs remplacent les libellés fonctionnels quand un
  appel court au modèle peut être validé de manière déterministe.

Aucun intertitre n'est accepté s'il introduit un mot important absent de la
section correspondante. En cas d'échec API ou de validation, le titre générique
reste en place : l'amélioration de forme ne doit jamais bloquer la publication.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from editorial_quality import ArticleRecord, Source, parse_article, significant_tokens

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
INDEX_PATH = ROOT / "data" / "articles.json"

_GENERIC_HEADINGS = {
    "les faits", "faits", "contexte", "le contexte", "debat et nuances",
    "debats et nuances", "nuances", "les nuances", "ce qu il faut savoir",
    "a retenir", "en bref", "pour comprendre", "ce qui change",
}
_STRONG_WORDS = {
    "historique", "inedit", "record", "revolutionnaire", "majeur",
    "exceptionnel", "spectaculaire", "alarmant", "inquietant", "decisif",
}
_PRIMARY_SUFFIXES = (
    ".gouv.fr", ".gov", ".europa.eu", ".int", "legifrance.gouv.fr",
    "insee.fr", "cnrs.fr", "inserm.fr", "inrae.fr", "pasteur.fr",
    "nasa.gov", "esa.int", "who.int", "doi.org",
)


@dataclass
class DepthResult:
    hard: list[str]
    warnings: list[str]
    novelty_context: float | None = None
    novelty_nuances: float | None = None


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", text or "", re.UNICODE))


def _novelty(section: str, previous: str) -> float:
    current = significant_tokens(section)
    before = significant_tokens(previous)
    if not current:
        return 1.0
    return len(current - before) / len(current)


def _max_sentence_similarity(section: str, previous: str) -> float:
    def sentences(text: str) -> list[str]:
        return [
            _norm(s) for s in re.split(r"(?<=[.!?…])\s+", text or "")
            if _word_count(s) >= 8
        ]

    current, before = sentences(section), sentences(previous)
    if not current or not before:
        return 0.0
    return max(SequenceMatcher(None, a, b).ratio() for a in current for b in before)


def section_depth(article: ArticleRecord) -> DepthResult:
    """Mesure si contexte et nuances font réellement progresser le texte."""
    hard: list[str] = []
    warnings: list[str] = []
    if article.format == "breve":
        return DepthResult(hard, warnings)

    facts = article.facts.strip()
    context = article.context.strip()
    nuances = article.nuances.strip()

    if not facts or _word_count(facts) < 80:
        hard.append("section factuelle trop mince pour un article long")

    if not context and not nuances:
        hard.append("article long sans contexte ni nuance documentée")
        return DepthResult(hard, warnings)

    novelty_context = None
    if context:
        novelty_context = _novelty(context, facts)
        similarity = _max_sentence_similarity(context, facts)
        if _word_count(context) >= 45 and novelty_context < 0.24:
            hard.append(f"contexte trop redondant avec les faits ({novelty_context:.0%} de matière nouvelle)")
        elif novelty_context < 0.34:
            warnings.append(f"contexte peu distinct ({novelty_context:.0%} de matière nouvelle)")
        if similarity >= 0.86:
            hard.append("une phrase du contexte répète presque mot pour mot les faits")

    novelty_nuances = None
    if nuances:
        before = " ".join(x for x in (facts, context) if x)
        novelty_nuances = _novelty(nuances, before)
        similarity = _max_sentence_similarity(nuances, before)
        if _word_count(nuances) >= 40 and novelty_nuances < 0.24:
            hard.append(f"nuances trop redondantes ({novelty_nuances:.0%} de matière nouvelle)")
        elif novelty_nuances < 0.34:
            warnings.append(f"nuances peu distinctes ({novelty_nuances:.0%} de matière nouvelle)")
        if similarity >= 0.86:
            hard.append("une phrase des nuances répète presque mot pour mot une section précédente")

    # Un article long ne doit pas être une brève artificiellement étirée.
    total = _word_count(article.body)
    if total < 300:
        hard.append(f"article long trop court ({total} mots) : utiliser le format brève")

    return DepthResult(hard, warnings, novelty_context, novelty_nuances)


def _source_title_similarity(sources: list[Source]) -> float:
    titles = [_norm(s.title) for s in sources if _word_count(s.title) >= 5]
    if len(titles) < 3:
        return 0.0
    ratios = [
        SequenceMatcher(None, titles[i], titles[j]).ratio()
        for i in range(len(titles)) for j in range(i + 1, len(titles))
    ]
    return sum(ratios) / len(ratios) if ratios else 0.0


def _has_primary_source(sources: Iterable[Source]) -> bool:
    for source in sources:
        try:
            host = (urlsplit(source.url).hostname or "").lower()
        except Exception:
            continue
        if any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _PRIMARY_SUFFIXES):
            return True
    return False


def sourcing_warning(article: ArticleRecord) -> str | None:
    """Alerte mesurable, non bloquante, sur une probable même dépêche."""
    similarity = _source_title_similarity(article.sources)
    if len(article.sources) >= 3 and similarity >= 0.78 and not _has_primary_source(article.sources):
        return (
            f"les {len(article.sources)} titres de sources sont très proches "
            f"({similarity:.0%}) et aucune source primaire n'est présente"
        )
    return None


def validate_heading(heading: str, section: str) -> bool:
    heading = (heading or "").strip()
    norm = _norm(heading)
    words = heading.split()
    if not 3 <= len(words) <= 12 or len(heading) > 92:
        return False
    if norm in _GENERIC_HEADINGS or heading.endswith(("?", "!")):
        return False
    if re.search(r"\b(?:selon|d'apres)\b", norm):
        return False

    h_tokens = significant_tokens(heading)
    s_tokens = significant_tokens(section)
    if not h_tokens or not s_tokens or not (h_tokens & s_tokens):
        return False

    # Les adjectifs les plus risqués ne sont admis que s'ils figurent déjà dans
    # la section : un intertitre ne doit jamais amplifier le texte.
    for strong in _STRONG_WORDS:
        if strong in norm and strong not in _norm(section):
            return False
    return True


def _groq_keys() -> list[str]:
    values = [os.getenv("GROQ_API_KEY", "")]
    values.extend(os.getenv(f"GROQ_API_KEY_{i}", "") for i in range(2, 41))
    return [v for v in values if v]


def generate_headings(article: ArticleRecord) -> dict[str, str]:
    """Un très petit appel de titraille, avec validation stricte en aval."""
    keys = _groq_keys()
    if not keys or article.format == "breve":
        return {}

    sections = {
        "faits": article.facts[:1800],
        "contexte": article.context[:1500],
        "nuances": article.nuances[:1500],
    }
    sections = {k: v for k, v in sections.items() if v.strip()}
    if not sections:
        return {}

    system = (
        "Tu es un secrétaire de rédaction. Produis uniquement des intertitres "
        "informatifs en français pour les sections fournies. Tu n'ajoutes aucun "
        "fait, aucun chiffre, aucun nom et aucun jugement absent du texte. "
        "Chaque intertitre fait 3 à 12 mots, sans point final, sans question et "
        "sans formule générique comme 'Les faits', 'Contexte' ou 'À retenir'. "
        "Réponds uniquement par un objet JSON dont les clés sont celles reçues."
    )
    user = json.dumps({"titre_article": article.title, "sections": sections}, ensure_ascii=False)

    try:
        from pipeline import _client
    except Exception:
        return {}

    model = os.getenv("EDITORIAL_HEADINGS_MODEL", "") or os.getenv("GROQ_MODEL_OVERRIDE", "") or "llama-3.3-70b-versatile"
    last_error: Exception | None = None
    for key in keys:
        try:
            response = _client(key).chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.15,
                max_tokens=260,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {}
            valid: dict[str, str] = {}
            for key_name, section in sections.items():
                candidate = data.get(key_name, "")
                if isinstance(candidate, str) and validate_heading(candidate, section):
                    valid[key_name] = candidate.strip()
            return valid
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        print(f"::warning::[INTERTITRES] Appel indisponible : {last_error}")
    return {}


def apply_headings(article: ArticleRecord, headings: dict[str, str]) -> bool:
    if not headings:
        return False
    soup = BeautifulSoup(article.path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    changed = False
    for h2 in soup.select("h2.art__h2"):
        label = _norm(h2.get_text(" ", strip=True))
        key = "faits"
        if "contexte" in label:
            key = "contexte"
        elif "nuance" in label or "debat" in label:
            key = "nuances"
        candidate = headings.get(key)
        section_text = getattr(article, {"faits": "facts", "contexte": "context", "nuances": "nuances"}[key])
        if candidate and validate_heading(candidate, section_text):
            h2.string = candidate
            h2["data-section"] = key
            changed = True
    if changed:
        article.path.write_text(str(soup), encoding="utf-8")
    return changed


def _changed_article_paths() -> set[Path]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "articles"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    except Exception:
        return set()
    out: set[Path] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip().split(" -> ")[-1]
        path = (ROOT / raw).resolve()
        if path.suffix == ".html" and path.exists():
            out.add(path)
    return out


def _load_index() -> list[dict]:
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _remove(article: ArticleRecord, index: list[dict]) -> None:
    article.path.unlink(missing_ok=True)
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        (ROOT / "assets" / "images" / f"{article.slug}{ext}").unlink(missing_ok=True)
    index[:] = [item for item in index if item.get("slug") != article.slug]


def process_editorial_depth(root: Path | None = None) -> dict:
    global ROOT, ARTICLES_DIR, INDEX_PATH
    if root is not None:
        ROOT = Path(root).resolve()
        ARTICLES_DIR = ROOT / "articles"
        INDEX_PATH = ROOT / "data" / "articles.json"

    changed = _changed_article_paths()
    if not changed:
        return {"checked": 0, "removed": 0, "headings": 0, "needs_rebuild": False}

    index = _load_index()
    meta = {str(item.get("slug")): item for item in index}
    records: list[ArticleRecord] = []
    for path in sorted(changed):
        records.append(parse_article(path, meta.get(path.stem), is_new=True))

    removed = 0
    survivors: list[ArticleRecord] = []
    for article in records:
        result = section_depth(article)
        warning = sourcing_warning(article)
        for message in result.warnings:
            print(f"::warning file=articles/{article.slug}.html::[PROFONDEUR] {message}")
        if warning:
            print(f"::warning file=articles/{article.slug}.html::[INDÉPENDANCE SOURCES] {warning}")
        if result.hard:
            print(
                f"::error file=articles/{article.slug}.html::[REJET PROFONDEUR] "
                + " ; ".join(result.hard)
            )
            _remove(article, index)
            removed += 1
        else:
            survivors.append(article)

    if removed:
        INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    changed_headings = 0
    for article in survivors:
        if article.format == "breve":
            continue
        headings = generate_headings(article)
        if apply_headings(article, headings):
            changed_headings += 1
            print(f"[INTERTITRES] ✓ {article.slug} : {', '.join(headings.values())}")
        elif headings:
            print(f"::warning file=articles/{article.slug}.html::[INTERTITRES] Sortie partielle refusée")

    print(
        f"[PROFONDEUR] {len(records)} article(s) contrôlé(s), {removed} rejeté(s), "
        f"{changed_headings} avec intertitres éditoriaux."
    )
    return {
        "checked": len(records), "removed": removed, "headings": changed_headings,
        "needs_rebuild": bool(removed),
    }


if __name__ == "__main__":
    process_editorial_depth()
