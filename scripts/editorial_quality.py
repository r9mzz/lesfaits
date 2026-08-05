# -*- coding: utf-8 -*-
"""Garde éditorial déterministe exécuté après chaque génération.

Objectifs :
- empêcher deux articles sur le même événement dans un même lot ;
- bloquer les contradictions temporelles et répétitions manifestes ;
- transformer les attributions en notes numérotées, sans modifier les faits ;
- employer des libellés publics exacts (sources consultées, contrôle automatisé).

Le script ne crée aucun fait et ne réécrit pas le fond. En cas de doute, il
rejette le nouvel article plutôt que de publier un texte fragile.
"""
from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
INDEX_PATH = ROOT / "data" / "articles.json"

_STOPWORDS = {
    "alors", "apres", "avec", "avoir", "avant", "chez", "comme", "dans",
    "depuis", "devant", "elle", "elles", "entre", "etre", "fait", "faire",
    "leurs", "mais", "meme", "pour", "sans", "selon", "sous", "sur", "tous",
    "tout", "toute", "toutes", "vers", "plus", "moins", "cette", "ceux",
    "cela", "celui", "celle", "dont", "ainsi", "aussi", "encore", "peut",
    "pourrait", "doit", "devrait", "nouveau", "nouvelle", "nouveaux",
    "article", "annonce", "actualite", "information", "resultat", "resultats",
    "france", "francais", "francaise", "mercredi", "jeudi", "vendredi",
    "samedi", "dimanche", "lundi", "mardi", "aout", "juillet", "juin",
}

_FUTURE_RE = re.compile(
    r"\b(?:devait|devra|devrait|doit|va|vont|sera|seront|laissera|prévoit|prévu(?:e|s|es)?|"
    r"attendu(?:e|s|es)?|s['’]apprête|à venir|prochainement)\b",
    re.I,
)
_PAST_RE = re.compile(
    r"\b(?:a été|ont été|s['’]est|se sont|a eu lieu|ont eu lieu|a percuté|"
    r"a annoncé|ont annoncé|a publié|ont publié|est survenu|sont survenus|"
    r"a commencé|a pris fin|a interdit|ont interdit)\b",
    re.I,
)
_TRANSITION_RE = re.compile(
    r"\b(?:puis|finalement|désormais|entre-temps|depuis|après avoir|plus tôt|"
    r"initialement|auparavant|dans un premier temps|ensuite)\b",
    re.I,
)
_FILLER_RE = re.compile(
    r"\b(?:il est important de noter|dans les années à venir|pourrait révolutionner|"
    r"pourrait avoir des implications|suscite l['’]intérêt des chercheurs|"
    r"des recherches supplémentaires sont nécessaires|il reste difficile de prévoir|"
    r"seul l['’]avenir dira)\b",
    re.I,
)
_UNPROVEN_BIG_WORDS_RE = re.compile(
    r"\b(?:inédit(?:e)?|sans précédent|révolutionnaire|historique|record|majeur(?:e)?)\b",
    re.I,
)


@dataclass
class Source:
    name: str
    title: str
    url: str


@dataclass
class ArticleRecord:
    path: Path
    slug: str
    title: str
    lead: str
    facts: str
    context: str
    nuances: str
    date_iso: str
    sources: list[Source] = field(default_factory=list)
    format: str = "article"
    words: int = 0
    verification: str = ""
    is_new: bool = False

    @property
    def body(self) -> str:
        return " ".join(x for x in (self.lead, self.facts, self.context, self.nuances) if x)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def significant_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", _norm(text)):
        if len(word) < 4 or word in _STOPWORDS:
            continue
        # Préfixe suffisamment long pour rapprocher singulier/pluriel et
        # variantes simples, sans fusionner des mots courts sans rapport.
        out.add(word[:9])
    return out


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlsplit(url)
        host = p.netloc.lower().removeprefix("www.")
        path = re.sub(r"/+$", "", p.path)
        return urlunsplit((p.scheme.lower() or "https", host, path, "", ""))
    except Exception:
        return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def same_event(a: ArticleRecord, b: ArticleRecord) -> bool:
    """Détection conservatrice : un signal éditorial ET un signal documentaire.

    Une simple collision de deux mots n'est jamais suffisante. Les critères les
    plus forts sont le partage d'une URL source et la proximité du titre ; sans
    URL commune, le seuil lexical est volontairement élevé et limité au même jour.
    """
    ta, tb = significant_tokens(a.title), significant_tokens(b.title)
    shared = ta & tb
    title_j = _jaccard(ta, tb)
    title_ratio = SequenceMatcher(None, _norm(a.title), _norm(b.title)).ratio()

    urls_a = {_canonical_url(s.url) for s in a.sources if s.url}
    urls_b = {_canonical_url(s.url) for s in b.sources if s.url}
    source_overlap = bool(urls_a & urls_b)

    source_titles_a = significant_tokens(" ".join(s.title for s in a.sources))
    source_titles_b = significant_tokens(" ".join(s.title for s in b.sources))
    source_title_j = _jaccard(source_titles_a, source_titles_b)

    same_day = bool(a.date_iso and b.date_iso and a.date_iso[:10] == b.date_iso[:10])

    if source_overlap and len(shared) >= 2:
        return True
    if source_overlap and (title_j >= 0.25 or source_title_j >= 0.45):
        return True
    if same_day and len(shared) >= 3 and title_j >= 0.42:
        return True
    if same_day and len(shared) >= 2 and title_ratio >= 0.76 and source_title_j >= 0.30:
        return True
    return False


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text or "") if s.strip()]


def timeline_conflict(text: str) -> bool:
    """Vrai si le même passage mélange futur et accompli sans articulation."""
    for paragraph in re.split(r"\n+", text or ""):
        if _FUTURE_RE.search(paragraph) and _PAST_RE.search(paragraph):
            if not _TRANSITION_RE.search(paragraph):
                return True
    return False


def repeated_statement(text: str) -> bool:
    sentences = [_norm(s) for s in _sentences(text) if len(significant_tokens(s)) >= 5]
    seen: set[str] = set()
    ngrams_seen: set[tuple[str, ...]] = set()
    for sentence in sentences:
        compact = re.sub(r"^(selon|d'apres)\s+[^,]{2,100},\s*", "", sentence)
        if compact in seen:
            return True
        seen.add(compact)
        words = [w for w in re.findall(r"[a-z0-9]+", compact) if w not in _STOPWORDS]
        current = {tuple(words[i:i + 5]) for i in range(max(0, len(words) - 4))}
        if current & ngrams_seen:
            return True
        ngrams_seen |= current
    return False


def quality_issues(article: ArticleRecord) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    warnings: list[str] = []
    main_text = " ".join(x for x in (article.lead, article.facts) if x)
    if timeline_conflict(main_text):
        hard.append("chronologie contradictoire (futur et événement accompli sans transition)")
    if repeated_statement(article.body):
        hard.append("information répétée mot pour mot ou quasi mot pour mot")
    filler_count = len(_FILLER_RE.findall(article.body))
    if filler_count >= 2 or (article.format == "breve" and filler_count >= 1):
        hard.append(f"remplissage générique ({filler_count} formule(s))")
    if _UNPROVEN_BIG_WORDS_RE.search(article.title + " " + article.lead):
        source_titles = " ".join(s.title for s in article.sources)
        if not _UNPROVEN_BIG_WORDS_RE.search(source_titles):
            warnings.append("qualificatif fort absent des titres de sources")
    return hard, warnings


def _load_index() -> list[dict]:
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _changed_article_paths() -> set[Path]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "articles"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    except Exception:
        return set()
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        p = ROOT / raw
        if p.suffix == ".html" and p.exists():
            paths.add(p.resolve())
    return paths


def _section_texts(soup: BeautifulSoup) -> dict[str, str]:
    sections = {"facts": "", "context": "", "nuances": ""}
    for h2 in soup.select("h2.art__h2"):
        label = _norm(h2.get_text(" ", strip=True))
        p = h2.find_next_sibling("p")
        if not p:
            continue
        text = p.get_text(" ", strip=True)
        if "contexte" in label:
            sections["context"] = text
        elif "nuance" in label or "debat" in label:
            sections["nuances"] = text
        else:
            sections["facts"] = text
    return sections


def parse_article(path: Path, metadata: dict | None = None, *, is_new: bool = False) -> ArticleRecord:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    metadata = metadata or {}
    sections = _section_texts(soup)
    sources: list[Source] = []
    for li in soup.select("section.sources li"):
        cite = li.find("cite")
        em = li.find("em")
        link = li.find("a", href=True)
        sources.append(Source(
            name=cite.get_text(" ", strip=True) if cite else "",
            title=em.get_text(" ", strip=True) if em else "",
            url=link.get("href", "") if link else "",
        ))
    time_el = soup.find("time")
    date_iso = time_el.get("datetime", "") if time_el else ""
    title_el = soup.select_one("h1.art__title")
    lead_el = soup.select_one("p.art__resume")
    return ArticleRecord(
        path=path,
        slug=path.stem,
        title=title_el.get_text(" ", strip=True) if title_el else metadata.get("titre", ""),
        lead=lead_el.get_text(" ", strip=True) if lead_el else "",
        facts=sections["facts"], context=sections["context"], nuances=sections["nuances"],
        date_iso=date_iso, sources=sources,
        format=str(metadata.get("format") or "article"),
        words=int(metadata.get("nb_mots") or 0),
        verification=str(metadata.get("statut_verification") or ""),
        is_new=is_new,
    )


def _quality_score(article: ArticleRecord) -> float:
    score = 0.0
    if not article.is_new:
        score += 10_000  # ne jamais retirer automatiquement un article déjà publié
    if article.format == "article":
        score += 120
    score += len(article.sources) * 25
    score += min(article.words, 1000) / 10
    if article.verification == "conforme_du_premier_coup":
        score += 10
    elif article.verification == "corrige_automatiquement":
        score += 5
    return score


def _remove_article(article: ArticleRecord, index: list[dict]) -> None:
    try:
        article.path.unlink(missing_ok=True)
    except Exception:
        pass
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        (ROOT / "assets" / "images" / f"{article.slug}{ext}").unlink(missing_ok=True)
    index[:] = [item for item in index if item.get("slug") != article.slug]


def _source_name_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    names = sorted({n.strip() for n in names if n.strip()}, key=len, reverse=True)
    if not names:
        return None
    alt = "(?:" + "|".join(re.escape(n) for n in names) + ")"
    return re.compile(
        rf"^\s*(?:Selon|D['’]après)\s+(?P<names>{alt}(?:\s*,\s*{alt})*(?:\s+et\s+{alt})?)\s*,\s*(?P<body>.+)$",
        re.I | re.S,
    )


def _capitalize_first(text: str) -> str:
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch.isalpha():
            chars[i] = ch.upper()
            break
    return "".join(chars)


def annotate_attributions(text: str, sources: list[Source]) -> str:
    """Convertit les attributions de début de phrase en appels de notes HTML."""
    pattern = _source_name_pattern(s.name for s in sources)
    if not pattern:
        return text
    source_map = {_norm(s.name): i + 1 for i, s in enumerate(sources) if s.name}
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?…])(?=\s|$)", text or ""):
        leading = sentence[:len(sentence) - len(sentence.lstrip())]
        core = sentence.strip()
        match = pattern.match(core)
        if not match:
            out.append(sentence)
            continue
        nums: list[int] = []
        names_part = match.group("names")
        for source in sources:
            if re.search(rf"(?<!\w){re.escape(source.name)}(?!\w)", names_part, re.I):
                number = source_map.get(_norm(source.name))
                if number and number not in nums:
                    nums.append(number)
        if not nums:
            out.append(sentence)
            continue
        body = _capitalize_first(match.group("body").strip())
        punct_match = re.search(r"([.!?…]+)$", body)
        punct = punct_match.group(1) if punct_match else ""
        if punct:
            body = body[:-len(punct)]
        refs = "".join(
            f'<a href="#source-{n}" aria-label="Source {n}">{n}</a>' for n in nums
        )
        out.append(f'{leading}{body}<sup class="cite-ref">{refs}</sup>{punct}')
    return "".join(out)


def _install_citation_style(soup: BeautifulSoup) -> None:
    if soup.find("style", id="lf-citations"):
        return
    style = soup.new_tag("style", id="lf-citations")
    style.string = (
        ".cite-ref{font-size:.68em;vertical-align:super;margin-left:.18em;font-weight:700}"
        ".cite-ref a{color:var(--blue);text-decoration:none;margin-right:.14em}"
        ".cite-ref a:hover{text-decoration:underline}.sources li:target{background:rgba(108,133,189,.10);"
        "outline:2px solid rgba(108,133,189,.35);outline-offset:4px;border-radius:2px}"
    )
    if soup.head:
        soup.head.append(style)


def improve_article_html(article: ArticleRecord) -> None:
    soup = BeautifulSoup(article.path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    source_items = soup.select("section.sources li")
    for i, li in enumerate(source_items, 1):
        li["id"] = f"source-{i}"
    _install_citation_style(soup)

    # On ne touche qu'aux paragraphes éditoriaux simples. Les blocs contenant
    # déjà des balises complexes sont laissés intacts.
    paragraphs = list(soup.select("p.art__resume"))
    for h2 in soup.select("h2.art__h2"):
        p = h2.find_next_sibling("p")
        if p:
            paragraphs.append(p)
    for p in paragraphs:
        if p.find(True):
            continue
        original = p.get_text()
        annotated = annotate_attributions(original, article.sources)
        if annotated != original:
            fragment = BeautifulSoup(annotated, "html.parser")
            p.clear()
            for node in list(fragment.contents):
                p.append(node)

    html = str(soup)
    html = re.sub(r"(\d+)\s+sources?\s+vérifiées", r"\1 sources consultées", html, flags=re.I)
    html = re.sub(r"(\d+)\s+sources?\s+vérifié(?:e|es)?", r"\1 sources consultées", html, flags=re.I)
    html = html.replace(
        "Le fact-check automatisé n'a relevé aucune anomalie : article publié tel que généré.",
        "Le contrôle automatisé n'a détecté aucun défaut bloquant : article publié tel que généré.",
    )
    html = html.replace(
        "Le fact-check automatisé n’a relevé aucune anomalie : article publié tel que généré.",
        "Le contrôle automatisé n’a détecté aucun défaut bloquant : article publié tel que généré.",
    )
    html = re.sub(
        r"(\d+) sources distinctes — (\d+) médias de référence",
        r"\1 publications consultées — \2 médias de référence",
        html,
    )
    article.path.write_text(html, encoding="utf-8")


def process_generated_articles(root: Path | None = None) -> dict:
    global ROOT, ARTICLES_DIR, INDEX_PATH
    if root is not None:
        ROOT = Path(root).resolve()
        ARTICLES_DIR = ROOT / "articles"
        INDEX_PATH = ROOT / "data" / "articles.json"

    changed = _changed_article_paths()
    if not changed:
        print("[GARDE ÉDITORIAL] Aucun nouvel article à contrôler.")
        return {"new": 0, "removed": 0, "improved": 0, "needs_rebuild": False}

    index = _load_index()
    meta = {str(item.get("slug")): item for item in index}
    records: list[ArticleRecord] = []
    for path in sorted(ARTICLES_DIR.glob("*.html")):
        try:
            records.append(parse_article(path, meta.get(path.stem), is_new=path.resolve() in changed))
        except Exception as exc:
            if path.resolve() in changed:
                raise RuntimeError(f"Impossible d'analyser le nouvel article {path.name}: {exc}") from exc

    new_records = [r for r in records if r.is_new]
    to_remove: dict[str, tuple[ArticleRecord, str]] = {}

    # Détection des doublons : on compare chaque nouveau texte au corpus récent
    # et aux autres textes du même lot. Un article existant l'emporte toujours.
    recent = records[:250]
    for article in new_records:
        if article.slug in to_remove:
            continue
        for other in recent:
            if other.slug == article.slug or other.slug in to_remove:
                continue
            if not (article.is_new or other.is_new):
                continue
            if not same_event(article, other):
                continue
            winner = max((article, other), key=_quality_score)
            loser = other if winner.slug == article.slug else article
            if loser.is_new:
                to_remove[loser.slug] = (
                    loser,
                    f"doublon du même événement avec « {winner.title} »",
                )
            if loser.slug == article.slug:
                break

    # Contrôles de qualité déterministes sur les survivants.
    for article in new_records:
        if article.slug in to_remove:
            continue
        hard, warnings = quality_issues(article)
        for warning in warnings:
            print(f"::warning file=articles/{article.slug}.html::[GARDE ÉDITORIAL] {warning}")
        if hard:
            to_remove[article.slug] = (article, " ; ".join(hard))

    for article, reason in to_remove.values():
        print(f"::error file=articles/{article.slug}.html::[REJET ÉDITORIAL] {reason}")
        _remove_article(article, index)

    if to_remove:
        INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    improved = 0
    for article in new_records:
        if article.slug in to_remove or not article.path.exists():
            continue
        improve_article_html(article)
        improved += 1
        print(f"[GARDE ÉDITORIAL] ✓ {article.slug} : notes numérotées + libellés transparents")

    print(
        f"[GARDE ÉDITORIAL] {len(new_records)} nouveau(x), "
        f"{len(to_remove)} rejeté(s), {improved} amélioré(s)."
    )
    return {
        "new": len(new_records), "removed": len(to_remove), "improved": improved,
        "needs_rebuild": bool(to_remove),
    }


if __name__ == "__main__":
    process_generated_articles()
