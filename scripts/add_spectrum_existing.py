"""Ajoute le bloc spectrum aux articles existants via Groq."""
import sys, os, re, json
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()
ROOT = Path(__file__).parent.parent
client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

COLORS = ["#4a90d9", "#e57373", "#66bb6a", "#ffa726", "#ab47bc"]

SPECTRUM_PROMPT = """A partir du texte d'article fourni, identifie 2 à 4 acteurs réels cités et leur position sur le sujet traité.
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après :
{
  "label_gauche": "Ex: Pour la mesure / Favorable / Consensus",
  "label_droite": "Ex: Contre la mesure / Critique / En débat",
  "acteurs": [
    {"nom": "Nom acteur", "detail": "Sa position en 8 mots max", "position": 20},
    {"nom": "Nom acteur 2", "detail": "Sa position en 8 mots max", "position": 70}
  ]
}
position = 0 (totalement pour/favorable) à 100 (totalement contre/critique)."""


def build_spectrum_html(positions: dict) -> str:
    if not positions or not positions.get("acteurs"):
        return ""
    acteurs = positions["acteurs"]
    label_g = positions.get("label_gauche", "Favorable")
    label_d = positions.get("label_droite", "Critique")
    markers = "\n".join(
        f'<div class="spectrum__marker" style="left:{a["position"]}%">'
        f'<span class="spectrum__marker-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    legend_items = "\n".join(
        f'<div class="spectrum__legend-item">'
        f'<span class="spectrum__legend-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'<span class="spectrum__legend-name">{a["nom"]}</span>'
        f'<span class="spectrum__legend-sub">{a.get("detail","")}</span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    return (
        f'<div class="spectrum">\n'
        f'  <div class="spectrum__title">POSITIONS DES ACTEURS</div>\n'
        f'  <div class="spectrum__labels"><span>{label_g}</span><span>{label_d}</span></div>\n'
        f'  <div class="spectrum__track">{markers}</div>\n'
        f'  <div class="spectrum__legend">{legend_items}</div>\n'
        f'</div>'
    )


for p in sorted((ROOT / "articles").glob("*.html")):
    text = p.read_text(encoding="utf-8")
    if "spectrum" in text:
        print(f"  SKIP (déjà) {p.name}")
        continue

    # Extraire le contenu texte brut de l'article
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")
    article_text = soup.get_text(separator=" ", strip=True)[:3000]

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=400,
            temperature=0.1,
            messages=[
                {"role": "system", "content": SPECTRUM_PROMPT},
                {"role": "user", "content": article_text},
            ],
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
        positions = json.loads(raw.strip())
        spectrum_html = build_spectrum_html(positions)
        if spectrum_html:
            # Insérer avant <div class="sources">
            new_text = text.replace('<div class="sources">', spectrum_html + '\n  <div class="sources">', 1)
            p.write_text(new_text, encoding="utf-8")
            print(f"  OK {p.name}")
        else:
            print(f"  VIDE {p.name}")
    except Exception as e:
        print(f"  ERREUR {p.name}: {e}")

print("\nTerminé.")
