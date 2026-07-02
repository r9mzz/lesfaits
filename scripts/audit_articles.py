"""
Les Faits — Audit rétroactif des articles publiés
==================================================
Pour chaque article publié :
  1. extrait le texte et la liste officielle des sources ;
  2. détection déterministe : attributions « Selon X / D'après X » absentes de
     la liste de sources, formules vagues non sourcées, compteur de sources
     incohérent avec le badge affiché ;
  3. si ANTHROPIC_API_KEY est défini, fait AUSSI tourner la passe 2 complète
     (fact-checker claude-sonnet-4-6, cf. verification.py) sur le JSON de
     l'article reconstruit depuis le HTML ;
  4. vérifie tous les liens internes de la page ;
  5. génère rapport-audit.md, articles les plus problématiques en premier.

NE CORRIGE RIEN : la décision de corriger/réécrire/supprimer reste humaine.

Usage : python scripts/audit_articles.py
"""

import re, os, json, unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
ARTICLES = ROOT / "articles"
RAPPORT = ROOT / "rapport-audit.md"

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Formules d'attribution vagues : jamais acceptables sans nom précis
VAGUE_PATTERNS = [
    r"les experts", r"des experts", r"les sources", r"des études", r"les études",
    r"les chercheurs", r"des chercheurs", r"les spécialistes", r"les scientifiques",
    r"les données disponibles", r"les données recueillies", r"il est établi",
    r"les observateurs", r"les analystes", r"certains experts",
]

# Attributions génériques renvoyant à un document décrit dans le texte
# (pas un nom propre) — comptées séparément, moins graves
GENERIC_PATTERNS = [
    r"le décret", r"la loi", r"le rapport", r"l'étude", r"l'enquête",
    r"le communiqué", r"les résultats", r"le texte", r"la tribune",
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"^(le |la |les |l'|l’|un |une |des |du |de la |de |d'|d’)+", "", s)
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def extract_article(path: Path) -> dict:
    html = path.read_text(encoding="utf-8", errors="replace")

    # Sources officielles : <strong>X</strong> ou <cite>X</cite> dans le bloc sources
    src_block = re.search(
        r'<(?:div|section) class="sources[^"]*"[^>]*>(.*?)</(?:div|section)>',
        html, re.DOTALL)
    sources = []
    if src_block:
        sources = re.findall(r"<(?:strong|cite)>([^<]+)</(?:strong|cite)>", src_block.group(1))
    nb_li = len(re.findall(r"<li>", src_block.group(1))) if src_block else 0

    # Badge « N sources vérifiées »
    badge = re.search(r"(\d+)\s+sources?\s+vérifi", html)
    badge_n = int(badge.group(1)) if badge else None

    # Corps de texte (resume + sections), balises retirées
    body_parts = re.findall(
        r'<p class="art__resume">(.*?)</p>|<h2[^>]*>[^<]*</h2>\s*<p[^>]*>(.*?)</p>',
        html, re.DOTALL)
    text = " ".join(x or y for x, y in body_parts)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    # Liens internes de la page
    links = [l for l in re.findall(r'(?:href|src)="([^"]+)"', html)
             if not l.startswith(("http", "#", "mailto:", "data:"))]

    return {"sources": sources, "nb_li": nb_li, "badge_n": badge_n,
            "text": text, "links": links}


def audit_attributions(text: str, sources: list[str]) -> tuple[list, list, list]:
    """Retourne (inventées, vagues, génériques)."""
    norm_sources = [_norm(s) for s in sources]
    inventees, vagues, generiques = [], [], []

    for m in re.finditer(r"(?:Selon|D['’]après)\s+([^,;.]{2,70})[,;.]", text):
        target = m.group(1).strip()
        tn = _norm(target)
        if not tn:
            continue
        if any(re.search(p, target.lower()) for p in VAGUE_PATTERNS):
            vagues.append(target)
            continue
        if any(re.fullmatch(p + r".*", target.lower()) for p in GENERIC_PATTERNS):
            generiques.append(target)
            continue
        # correspondance floue avec une source officielle (substring dans un sens ou l'autre)
        ok = any(tn in ns or ns in tn or
                 len(set(tn.split()) & set(ns.split())) >= 1 and
                 max(len(w) for w in (set(tn.split()) & set(ns.split())) or [""]) > 3
                 for ns in norm_sources)
        if not ok:
            inventees.append(target)

    def dedup(l):
        seen, out = set(), []
        for x in l:
            k = _norm(x)
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out

    return dedup(inventees), dedup(vagues), dedup(generiques)


def check_links(links: list[str]) -> list[str]:
    broken = []
    for l in links:
        p = l.split("?")[0].split("#")[0]
        if p in ("", "/") or "${" in p:
            continue
        target = (ROOT / p.lstrip("/")).resolve()
        # les liens relatifs ../x depuis articles/ pointent aussi sur la racine
        alt = (ARTICLES / p).resolve()
        if not target.exists() and not alt.exists():
            broken.append(l)
    return sorted(set(broken))


def claude_pass(art_data: dict, slug: str) -> dict | None:
    """Passe 2 complète via l'API si la clé est présente."""
    if not ANTHROPIC_KEY:
        return None
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from verification import detecter
    pseudo_art = {
        "slug": slug,
        "corps_texte": art_data["text"][:12000],
        "sources": [{"institution": s, "titre": "", "url": ""} for s in art_data["sources"]],
        "nb_sources": art_data["badge_n"],
    }
    try:
        return detecter(pseudo_art)
    except Exception as e:
        return {"erreur": str(e)}


def main():
    results = []
    files = sorted(ARTICLES.glob("*.html"))
    print(f"[AUDIT] {len(files)} articles")
    for f in files:
        slug = f.stem
        data = extract_article(f)
        inventees, vagues, generiques = audit_attributions(data["text"], data["sources"])
        broken = check_links(data["links"])
        compteur_ok = (data["badge_n"] is None) or (data["badge_n"] == data["nb_li"])
        rapport_claude = claude_pass(data, slug)

        score = 3 * len(inventees) + 2 * len(vagues) + len(broken) + (0 if compteur_ok else 2)
        if rapport_claude and not rapport_claude.get("erreur"):
            score += 2 * len(rapport_claude.get("problemes", []))

        results.append({
            "slug": slug, "score": score,
            "inventees": inventees, "vagues": vagues, "generiques": generiques,
            "liens_casses": broken, "compteur_ok": compteur_ok,
            "badge": data["badge_n"], "nb_li": data["nb_li"],
            "claude": rapport_claude,
        })

    results.sort(key=lambda r: -r["score"])
    conformes = [r for r in results if r["score"] == 0]

    lines = [
        "# Rapport d'audit — Les Faits",
        f"\nGénéré le {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
        f"{len(results)} articles audités · "
        f"passe Claude : {'OUI' if ANTHROPIC_KEY else 'NON (ANTHROPIC_API_KEY absent — détection déterministe uniquement)'}",
        f"\n**{len(results) - len(conformes)} articles avec problèmes · {len(conformes)} conformes**",
        "\n> Détection déterministe : attributions « Selon X / D'après X » comparées à la",
        "> liste officielle de sources de l'article. Une « attribution non vérifiable »",
        "> est un média/expert/institution cité dans le texte mais absent des sources.",
        "> Ce rapport ne corrige rien : chaque décision reste humaine.",
        "\n---",
    ]

    for r in results:
        if r["score"] == 0:
            continue
        lines.append(f"\n## {r['slug']}  (score {r['score']})")
        if r["inventees"]:
            lines.append(f"- **Attributions non vérifiables ({len(r['inventees'])})** : "
                         + " · ".join(f"« Selon {x} »" for x in r["inventees"]))
        if r["vagues"]:
            lines.append(f"- **Formules vagues ({len(r['vagues'])})** : "
                         + " · ".join(f"« {x} »" for x in r["vagues"]))
        if r["generiques"]:
            lines.append(f"- Attributions génériques ({len(r['generiques'])}) : "
                         + " · ".join(r["generiques"]))
        if not r["compteur_ok"]:
            lines.append(f"- **Compteur incohérent** : badge « {r['badge']} sources vérifiées » "
                         f"mais {r['nb_li']} sources listées")
        if r["liens_casses"]:
            lines.append(f"- **Liens internes cassés ({len(r['liens_casses'])})** : "
                         + " · ".join(r["liens_casses"]))
        if r["claude"] and not r["claude"].get("erreur"):
            for p in r["claude"].get("problemes", []):
                lines.append(f"- [Claude/{p.get('type','?')}] {p.get('phrase_exacte','')[:120]} — "
                             f"{p.get('explication','')}")

    lines.append(f"\n---\n\n## Articles conformes ({len(conformes)})\n")
    lines.append(", ".join(r["slug"] for r in conformes) or "(aucun)")

    RAPPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[AUDIT] rapport écrit : {RAPPORT}")
    print(f"[AUDIT] {len(results) - len(conformes)} articles avec problèmes, {len(conformes)} conformes")
    for r in results[:10]:
        if r["score"] > 0:
            print(f"  score {r['score']:>3}  {r['slug']}")


if __name__ == "__main__":
    main()
