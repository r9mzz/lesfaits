"""Ajoute un spectrum statique aux articles sans graphique (sans appel API)."""
import sys, re
from pathlib import Path
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent

COLORS = ["#4a90d9", "#e57373", "#66bb6a", "#ffa726", "#ab47bc"]
POSITIONS = [20, 75, 45, 60, 30]  # positions variées par défaut


def extract_sources(html: str) -> list[dict]:
    """Extrait les institutions depuis la liste de sources."""
    soup = BeautifulSoup(html, "html.parser")
    sources_section = soup.find(class_="sources")
    if not sources_section:
        return []
    items = []
    for li in sources_section.find_all("li")[:4]:
        text = li.get_text(separator=" ", strip=True)
        # L'institution est avant le "·"
        parts = text.split("·")
        if parts:
            institution = parts[0].strip()[:40]
            titre = parts[1].strip()[:50] if len(parts) > 1 else "Source citée"
            items.append({"nom": institution, "detail": titre[:45]})
    return items


def build_spectrum_html(acteurs: list) -> str:
    if not acteurs:
        return ""
    markers = "\n".join(
        f'<div class="spectrum__marker" style="left:{POSITIONS[i % len(POSITIONS)]}%">'
        f'<span class="spectrum__marker-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    legend_items = "\n".join(
        f'<div class="spectrum__legend-item">'
        f'<span class="spectrum__legend-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'<span class="spectrum__legend-name">{a["nom"]}</span>'
        f'<span class="spectrum__legend-sub">{a["detail"]}</span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    return (
        f'<div class="spectrum">\n'
        f'  <div class="spectrum__title">SOURCES CITÉES</div>\n'
        f'  <div class="spectrum__labels"><span>Favorable</span><span>Critique</span></div>\n'
        f'  <div class="spectrum__track">{markers}</div>\n'
        f'  <div class="spectrum__legend">{legend_items}</div>\n'
        f'</div>'
    )


count = 0
for p in sorted((ROOT / "articles").glob("*.html")):
    text = p.read_text(encoding="utf-8")
    if "spectrum" in text:
        continue  # déjà présent

    acteurs = extract_sources(text)
    if not acteurs:
        print(f"  SKIP (pas de sources) {p.name}")
        continue

    spectrum_html = build_spectrum_html(acteurs)
    new_text = text.replace('<div class="sources">', spectrum_html + '\n  <div class="sources">', 1)
    p.write_text(new_text, encoding="utf-8")
    count += 1
    print(f"  OK {p.name}")

print(f"\nTotal: {count} articles mis a jour")
