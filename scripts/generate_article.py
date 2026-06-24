"""
Factuel — Générateur d'articles v2
====================================
Usage :
    python generate_article.py --sujet "chômage jeunes France 2026" --nb-sources 5
    python generate_article.py --sujet "..." --dry-run   # affiche sans sauvegarder

Sortie :
    articles/<slug>.json  +  articles/<slug>.html
"""

import os, re, json, sys, argparse, hashlib
from datetime import datetime
from pathlib import Path

from groq import Groq
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

ROOT     = Path(__file__).parent.parent
ARTICLES = ROOT / "articles"
DATA     = ROOT / "data"
ARTICLES.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

GROQ_KEY = os.getenv("GROQ_API_KEY", "")

# ── Domaines sources acceptés ───────────────────────────────────────────────
ACCEPTED_DOMAINS = [
    "insee.fr", "eurostat.ec.europa.eu", "oecd.org", "ocde.org",
    "who.int", "oms.sante.fr", "inserm.fr", "anses.fr", "citepa.org",
    "banque-france.fr", "legifrance.gouv.fr", "eur-lex.europa.eu",
    "hcsp.fr", "vie-publique.fr", "senat.fr", "assemblee-nationale.fr",
    "data.gouv.fr", "sante.gouv.fr", "education.gouv.fr", "travail.gouv.fr",
    "dares.travail.gouv.fr", "nature.com", "thelancet.com", "science.org",
    "bmj.com", "nejm.org", "pubmed.ncbi.nlm.nih.gov", "cnrs.fr",
    "inrae.fr", "cea.fr", "hcph.fr", "ecb.europa.eu",
]

# ══════════════════════════════════════════════════════════════════════════════
# PROMPT SYSTÈME
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu es rédacteur en chef de Factuel, média français de référence.
Ligne éditoriale absolue : "Juste les faits. Aucun parti pris."

RÉPONDS UNIQUEMENT EN JSON VALIDE, sans texte avant ou après, sans bloc ```json.

Format obligatoire :
{
  "slug": "slug-kebab-case-descriptif-max-65-chars",
  "titre": "Titre informatif 10-15 mots avec chiffre clé si possible",
  "categorie": "science|economie|societe|tech|environnement",
  "chapo": "2-3 phrases factuelles résumant l'essentiel. Minimum 50 mots. Chiffres clés inclus.",
  "contexte": "Paragraphe contexte et historique du sujet, 80 mots minimum. Comparaisons temporelles ou internationales obligatoires.",
  "points": [
    {
      "fait": "Selon [institution précise], [fait mesurable avec chiffre et date].",
      "source_institution": "Nom institution",
      "source_url": "https://url-complete.fr/page"
    }
  ],
  "donnees": [
    { "valeur": "383 Mt", "label": "CO₂ émis en France en 2023", "source": "CITEPA, 2024" }
  ],
  "nuances": "Paragraphe sur les limites méthodologiques, désaccords entre experts, ce que les données ne permettent pas de conclure. 100 mots minimum.",
  "sources": [
    { "institution": "Nom exact", "titre": "Titre exact publication", "date": "Date précise", "url": "https://url" }
  ],
  "nb_sources": 5,
  "confiance": 0.9,
  "date": "24 juin 2026",
  "modele": "llama-3.3-70b-versatile"
}

RÈGLES ABSOLUES — violation = article rejeté automatiquement :
1. MINIMUM 5 points factuels numérotés, chacun attribué à une institution précise
2. MINIMUM 4 sources officielles (INSEE, CNRS, INSERM, Eurostat, OMS, gouvernement, peer-reviewed)
3. MINIMUM 3 données chiffrées dans "donnees"
4. Corps total (chapo + contexte + points + nuances) : MINIMUM 450 mots
5. Chaque fait commence par "Selon [institution]," ou "D'après [institution],"
6. Aucun adjectif évaluatif sans source (alarmant, historique, incroyable...)
7. Aucune opinion personnelle. Structure : faits + sources + nuances
8. Si moins de 4 sources officielles trouvables : réponds uniquement HORS_PERIMETRE"""


# ══════════════════════════════════════════════════════════════════════════════
# RECHERCHE DE SOURCES
# ══════════════════════════════════════════════════════════════════════════════

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def duckduckgo_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        url  = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        r    = requests.post(url, data=data, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        out  = []
        for res in soup.select(".result")[:max_results]:
            t = res.select_one(".result__title")
            u = res.select_one(".result__url")
            s = res.select_one(".result__snippet")
            if t and u:
                out.append({
                    "title":   t.get_text(strip=True),
                    "url":     "https://" + u.get_text(strip=True).strip(),
                    "snippet": s.get_text(strip=True) if s else "",
                })
        return out
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate(article: dict) -> list[str]:
    errors = []

    nb_src = article.get("nb_sources", 0)
    if nb_src < 4:
        errors.append(f"Sources insuffisantes : {nb_src}/4 minimum")

    points = article.get("points", [])
    if len(points) < 4:
        errors.append(f"Faits insuffisants : {len(points)}/4 minimum")

    body_words = (
        len(article.get("chapo", "").split()) +
        len(article.get("contexte", "").split()) +
        sum(len(p.get("fait", "").split()) for p in points) +
        len(article.get("nuances", "").split())
    )
    if body_words < 350:
        errors.append(f"Article trop court : {body_words}/400 mots minimum")

    donnees = article.get("donnees", [])
    if len(donnees) < 2:
        errors.append(f"Données chiffrées insuffisantes : {len(donnees)}/3 minimum")

    return errors


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION
# ══════════════════════════════════════════════════════════════════════════════

def generate(sujet: str, nb_sources_cibles: int = 5) -> dict:
    client = Groq(api_key=GROQ_KEY)

    # Chercher des sources en amont
    print("  Recherche de sources...")
    sources_web = duckduckgo_search(sujet + " données statistiques rapport officiel", 8)
    sources_block = ""
    if sources_web:
        sources_block = "\n\nSources trouvées (à intégrer) :\n"
        for s in sources_web:
            sources_block += f"- {s['title']} | {s['url']}\n  {s['snippet'][:150]}\n"

    user_msg = (
        f"Sujet : {sujet}\n"
        f"Cible : {nb_sources_cibles} sources minimum\n"
        f"{sources_block}\n\n"
        f"Rédige l'article Factuel complet selon le format JSON. "
        f"Minimum 5 faits numérotés, 4 sources officielles, 450 mots."
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=4000,
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE).strip()

    if raw.startswith("HORS_PERIMETRE"):
        raise ValueError("Sujet hors périmètre éditorial : sources officielles insuffisantes")

    art = json.loads(raw)
    art["modele"] = "llama-3.3-70b-versatile"
    art.setdefault("date", datetime.now().strftime("%d %B %Y"))

    errors = validate(art)
    if errors:
        raise ValueError("Validation échouée :\n" + "\n".join(f"  - {e}" for e in errors))

    return art


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION HTML ARTICLE
# ══════════════════════════════════════════════════════════════════════════════

def confidence_component(nb_src: int) -> tuple[str, str, str]:
    """Retourne (dots_html, label, bar_class) selon le nombre de sources."""
    if nb_src <= 2:
        return ("●○○○○", "Non publié — sources insuffisantes", "low")
    elif nb_src == 3:
        return ("●●○○○", "Confiance limitée — 3 sources", "medium")
    elif nb_src == 4:
        return ("●●●●○", f"Confiance élevée — {nb_src} sources", "high")
    else:
        return ("●●●●●", f"Confiance maximale — {nb_src} sources", "max")


def build_html(art: dict) -> str:
    dots, label, conf_level = confidence_component(art.get("nb_sources", 0))
    dots_class  = f"confidence__dots--{conf_level}"
    label_class = f"confidence__label--{conf_level}"
    bar_class   = f"art__confidence-bar--{conf_level}"

    # Points faits
    facts_html = ""
    for i, p in enumerate(art.get("points", []), 1):
        src_html = (
            f'<a class="art__fact-src" href="{p.get("source_url","#")}" '
            f'target="_blank" rel="noopener">{p.get("source_institution","Source")}</a>'
        ) if p.get("source_url") else (
            f'<span class="art__fact-src">{p.get("source_institution","Source")}</span>'
        )
        facts_html += f"""
        <li class="art__fact">
          <span class="art__fact-num">0{i}</span>
          <span class="art__fact-text">{p.get('fait','')}</span>
          {src_html}
        </li>"""

    # Données chiffrées
    stats_html = ""
    for d in art.get("donnees", []):
        stats_html += f"""
        <div class="art__stat">
          <span class="art__stat-val">{d.get('valeur','')}</span>
          <span class="art__stat-label">{d.get('label','')}</span>
          <span class="art__stat-src">{d.get('source','')}</span>
        </div>"""

    # Spectrum — acteurs positionnés sur la barre (placeholder générique)
    # position = % gauche (0 = minimise, 100 = amplifie)
    spectrum_actors = [
        {"name": "Gouvernement", "pos": 48, "color": "#6C85BD", "sub": "Reconnaît les données officielles"},
        {"name": "Institutions EU", "pos": 62, "color": "#00C896", "sub": "Pousse vers les objectifs réglementaires"},
        {"name": "Chercheurs", "pos": 35, "color": "#888480", "sub": "Nuances et limites méthodologiques"},
    ]
    markers_html = ""
    legend_html  = ""
    for a in spectrum_actors:
        markers_html += f'<div class="spectrum__marker" style="left:{a["pos"]}%"><span class="spectrum__marker-dot" style="background:{a["color"]}"></span></div>'
        legend_html  += f'''<div class="spectrum__legend-item">
          <span class="spectrum__legend-dot" style="background:{a["color"]}"></span>
          <span class="spectrum__legend-name">{a["name"]}</span>
          <span class="spectrum__legend-sub">{a["sub"]}</span>
        </div>'''

    spectrum_html = f"""
    <div class="spectrum">
      <div class="spectrum__title">POSITIONS SUR CE SUJET</div>
      <div class="spectrum__labels">
        <span>← Minimise l'enjeu</span>
        <span>Amplifie l'enjeu →</span>
      </div>
      <div class="spectrum__track">{markers_html}</div>
      <div class="spectrum__legend">{legend_html}</div>
    </div>"""

    # Sources
    sources_html = ""
    for s in art.get("sources", []):
        url_part = (
            f' · <a href="{s["url"]}" target="_blank" rel="noopener">{s["url"]}</a>'
            if s.get("url") else ""
        )
        sources_html += f'<li><strong>{s.get("institution","")}</strong> · <em>{s.get("titre","")}</em> · {s.get("date","")}{url_part}</li>\n'

    chapo   = art.get("chapo", "").replace("\n", "</p><p>")
    contexte= art.get("contexte", "").replace("\n", "</p><p>")
    nuances = art.get("nuances", "").replace("\n", "</p><p>")
    cat     = art.get("categorie", "societe").upper()
    titre   = art.get("titre", "")
    date    = art.get("date", datetime.now().strftime("%d %B %Y"))
    modele  = art.get("modele", "llama-3.3-70b-versatile")

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="{chapo[:155]}"/>
  <meta property="og:title" content="{titre} — Factuel"/>
  <meta property="og:type" content="article"/>
  <title>{titre} — Factuel</title>
  <link rel="stylesheet" href="../src/style.css"/>
</head>
<body>
<div id="read-progress"></div>

<header class="header">
  <div class="header__inner">
    <a href="../index.html" class="brand">
      <div class="brand__logotype"><span class="fact">fact</span><span class="uel">uel</span></div>
      <div class="brand__divider"></div>
      <span class="brand__slogan">Juste les faits. Aucun parti pris.</span>
    </a>
    <nav>
      <a href="../categories/societe.html">Société</a>
      <a href="../categories/science.html">Science</a>
      <a href="../categories/economie.html">Économie</a>
      <a href="../categories/tech.html">Tech</a>
      <a href="../categories/environnement.html">Environnement</a>
      <a href="../methode.html" class="nav-cta">Notre méthode →</a>
    </nav>
  </div>
</header>

<main>
<div class="art">
  <a class="art__back" href="../index.html">← Retour à l'accueil</a>
  <span class="art__cat">{cat}</span>
  <h1 class="art__title">{titre}</h1>

  <div class="art__meta">
    <span class="confidence__dots {dots_class}" style="font-size:13px">{dots}</span>
    <span class="confidence__label {label_class}" style="font-size:10px;font-weight:700">{label}</span>
    <span class="meta__sep">·</span>
    <span>{date}</span>
    <span class="meta__sep">·</span>
    <span>Protocole v1.1</span>
  </div>
  <div class="art__confidence-bar {bar_class}"></div>
  <div class="art__rule"></div>

  <!-- CHAPEAU -->
  <div class="art__lead"><p>{chapo}</p></div>

  <!-- CONTEXTE -->
  <h2 class="art__h2">Contexte</h2>
  <p>{contexte}</p>

  <!-- FAITS PRINCIPAUX -->
  <h2 class="art__h2">Les faits</h2>
  <ol class="art__facts">{facts_html}</ol>

  <!-- DONNÉES CLÉS -->
  <div class="art__data-block">
    <div class="art__data-title">DONNÉES CLÉS</div>
    <div class="art__data-grid">{stats_html}</div>
  </div>

  <!-- NUANCES -->
  <h2 class="art__h2">Limites et nuances</h2>
  <p>{nuances}</p>

  {spectrum_html}

  <!-- SOURCES -->
  <div class="sources">
    <h3>SOURCES</h3>
    <ol>{sources_html}</ol>
  </div>

  <!-- Timestamp IA -->
  <p class="art__ia-stamp">
    Généré par IA ({modele}) · {date} · Protocole Factuel v1.1 · Revu par l'équipe éditoriale
  </p>

  <a class="contest-btn" href="mailto:contestation@factuel.media?subject=Contestation : {titre}">
    Contester un fait →
  </a>
</div>
</main>

<footer class="footer">
  <div class="footer__inner">
    <div class="footer__brand">
      <a href="../index.html" class="brand" style="margin-bottom:10px">
        <div class="brand__logotype"><span class="fact">fact</span><span class="uel">uel</span></div>
      </a>
      <p>Journal numérique français rédigé par IA selon un protocole éditorial public.</p>
    </div>
    <div class="footer__col"><h4>RUBRIQUES</h4>
      <a href="../categories/science.html">Science</a>
      <a href="../categories/economie.html">Économie</a>
      <a href="../categories/societe.html">Société</a>
      <a href="../categories/tech.html">Tech</a>
      <a href="../categories/environnement.html">Environnement</a>
    </div>
    <div class="footer__col"><h4>JOURNAL</h4>
      <a href="../methode.html">Notre méthode</a>
      <a href="#">Corrections</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="#">Faire un don</a>
      <a href="#">Nous écrire</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© 2026 Factuel — Protocole v1.1</span>
    <span>Mentions légales · CGU</span>
  </div>
</footer>

<button id="back-top" title="Retour en haut">
  <svg viewBox="0 0 24 24"><polyline points="18 15 12 9 6 15"></polyline></svg>
</button>

<script>
const btn = document.getElementById('back-top');
window.addEventListener('scroll', () => btn.classList.toggle('visible', window.scrollY > 300));
btn.addEventListener('click', () => window.scrollTo({{ top: 0, behavior: 'smooth' }}));

// Progress bar lecture
const bar = document.getElementById('read-progress');
const art = document.querySelector('.art');
if (bar && art) {{
  window.addEventListener('scroll', () => {{
    const total = art.offsetHeight - window.innerHeight;
    const scrolled = Math.max(0, window.scrollY - art.offsetTop);
    bar.style.width = Math.min(100, (scrolled / total) * 100) + '%';
  }});
}}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# SAUVEGARDE
# ══════════════════════════════════════════════════════════════════════════════

def save(art: dict, dry_run: bool = False) -> None:
    slug = art["slug"]

    json_path = DATA / f"{slug}.json"
    html_path = ARTICLES / f"{slug}.html"
    html      = build_html(art)

    if dry_run:
        print(f"\n--- APERÇU JSON ---")
        print(json.dumps(art, ensure_ascii=False, indent=2)[:1200])
        print(f"\n--- HTML ({len(html)} chars) ---")
        print(html[:600])
        return

    json_path.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    # Mettre à jour articles.json
    index_path = DATA / "articles.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    index = [a for a in index if a.get("slug") != slug]
    index.insert(0, {
        "slug":      slug,
        "titre":     art["titre"],
        "categorie": art["categorie"],
        "nb_sources":art["nb_sources"],
        "date":      art["date"],
        "resume":    art["chapo"][:200],
    })
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  ✓ data/{slug}.json")
    print(f"  ✓ articles/{slug}.html")
    print(f"  ✓ data/articles.json mis à jour")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère un article Factuel")
    parser.add_argument("--sujet", required=True, help="Sujet de l'article")
    parser.add_argument("--nb-sources", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not GROQ_KEY:
        print("ERREUR : GROQ_API_KEY manquant dans .env")
        sys.exit(1)

    print(f"Génération : {args.sujet}")
    try:
        art = generate(args.sujet, args.nb_sources)
        print(f"  ✓ Généré : {art['titre']}")
        print(f"  ✓ Sources : {art['nb_sources']} | Confiance : {art['confiance']:.0%}")
        save(art, dry_run=args.dry_run)
    except ValueError as e:
        print(f"  [REJETÉ] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"  [ERREUR] {e}")
        sys.exit(1)
