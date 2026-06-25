"""
Les Faits — Script d'automatisation éditoriale
Protocole v1.1

Usage:
    python publish.py --input article.txt --category science
    python publish.py --url https://example.com/source --category economie
    python publish.py --draft chemin/vers/article.md --push
"""

import os
import re
import json
import argparse
from datetime import datetime, timezone

# pip install anthropic requests jwt
import anthropic
import requests
import jwt  # PyJWT


# ── Configuration ──────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GHOST_ADMIN_URL   = os.environ.get("GHOST_ADMIN_URL", "https://votre-site.ghost.io")
GHOST_ADMIN_KEY   = os.environ.get("GHOST_ADMIN_KEY", "")  # format id:secret

SYSTEM_PROMPT = """
# IDENTITÉ
Tu es l'IA rédactrice de Factuel, un journal numérique français dont la ligne éditoriale est :
"Juste les faits. Aucun parti pris."
Tu n'es pas un assistant. Tu es un rédacteur soumis à un protocole strict. Tu ne t'en écartes jamais.

# RÈGLE DE TRIAGE (v1.1)
Avant de rédiger, vérifie : "Existe-t-il des données mesurables et vérifiables sur ce sujet ?"
— OUI → rédige.
— NON → réponds uniquement : "HORS_PERIMETRE: [raison]"

# FORMAT DE SORTIE OBLIGATOIRE (JSON strict)
Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "titre": "...",
  "resume": ["phrase1", "phrase2", "phrase3"],
  "corps": {
    "faits": "...",
    "contexte": "...",
    "nuances": "..."
  },
  "sources": [
    {"institution": "...", "titre": "...", "date": "...", "url": "..."}
  ],
  "categorie": "science|economie|societe|tech|environnement|droit",
  "nb_sources": 0
}

# RÈGLES ABSOLUES
- Minimum 3 sources. Si insuffisant : ne pas rédiger.
- Interdiction d'inventer une source ou une donnée.
- Aucun adjectif évaluatif non sourcé (alarmant, scandaleux, historique…).
- Titre : descriptif, factuel, max 15 mots, sans point d'exclamation.
- Fait et opinion clairement séparés.
"""


# ── Étape 1 : Ingestion ────────────────────────────────────────────────────────

def ingest_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def ingest_url(url: str) -> str:
    """Récupère le contenu brut d'une URL (texte uniquement)."""
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Factuel-Bot/1.1"})
    resp.raise_for_status()
    # Extraction basique du texte — à remplacer par BeautifulSoup si besoin
    text = re.sub(r"<[^>]+>", " ", resp.text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:12000]  # limite de contexte raisonnable


# ── Étape 2 : Génération via Claude ───────────────────────────────────────────

def generate_article(source_content: str, category: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = (
        f"Catégorie demandée : {category}\n\n"
        f"Contenu source :\n\n{source_content}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    if raw.startswith("HORS_PERIMETRE"):
        raise ValueError(f"Sujet hors périmètre éditorial : {raw}")

    return json.loads(raw)


# ── Étape 3 : Mise en forme Markdown ──────────────────────────────────────────

def render_markdown(article: dict, date_pub: str) -> str:
    titre    = article["titre"]
    resume   = " ".join(article["resume"])
    faits    = article["corps"]["faits"]
    contexte = article["corps"]["contexte"]
    nuances  = article["corps"]["nuances"]
    sources  = article["sources"]
    categorie = article["categorie"].upper()
    nb_sources = article["nb_sources"]

    sources_md = "\n".join(
        f"{i+1}. {s['institution']} · {s['titre']} · {s['date']} · {s['url']}"
        for i, s in enumerate(sources)
    )

    return f"""# {titre}

**Résumé factuel**
{resume}

---

## Les faits

{faits}

## Contexte

{contexte}

## Débats et nuances

{nuances}

---

## Sources

{sources_md}

---

*Rédigé par IA · Protocole Les Faits v1.1 · {date_pub}*
*Catégorie : {categorie} · Sources vérifiées : {nb_sources}*
"""


def save_markdown(md: str, titre: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", titre.lower())[:60].strip("-")
    filename = f"drafts/{slug}.md"
    os.makedirs("drafts", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ Article sauvegardé : {filename}")
    return filename


# ── Étape 4 : Push vers Ghost CMS (brouillon) ─────────────────────────────────

def _ghost_jwt_token() -> str:
    """Génère un JWT signé pour l'API Admin Ghost."""
    key_id, secret = GHOST_ADMIN_KEY.split(":")
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 minutes
        "aud": "/admin/",
    }
    return jwt.encode(payload, bytes.fromhex(secret), algorithm="HS256",
                      headers={"kid": key_id})


def push_to_ghost(article: dict, markdown_content: str) -> dict:
    """
    Pousse l'article vers Ghost en statut 'draft'.
    Nécessite GHOST_ADMIN_URL et GHOST_ADMIN_KEY dans l'environnement.
    """
    if not GHOST_ADMIN_KEY:
        raise EnvironmentError("GHOST_ADMIN_KEY non défini. Export la variable d'environnement.")

    token = _ghost_jwt_token()
    url   = f"{GHOST_ADMIN_URL}/ghost/api/admin/posts/"

    # Ghost attend du HTML ou du Lexical JSON — on envoie en mobiledoc via markdown
    payload = {
        "posts": [{
            "title":  article["titre"],
            "slug":   re.sub(r"[^a-z0-9]+", "-", article["titre"].lower())[:60],
            "status": "draft",
            "tags":   [{"name": article["categorie"]}],
            "custom_excerpt": " ".join(article["resume"]),
            "mobiledoc": json.dumps({
                "version": "0.3.1",
                "atoms": [],
                "cards": [["markdown", {"markdown": markdown_content}]],
                "markups": [],
                "sections": [[10, 0]],
            }),
        }]
    }

    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    post = resp.json()["posts"][0]
    print(f"✓ Brouillon publié sur Ghost : {post['url']}")
    return post


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Les Faits — Pipeline éditorial IA")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input",  help="Chemin vers un fichier texte source")
    group.add_argument("--url",    help="URL d'une page source")
    group.add_argument("--draft",  help="Chemin vers un brouillon .md existant à pousser")
    parser.add_argument("--category", default="general", help="Catégorie éditoriale")
    parser.add_argument("--push",  action="store_true", help="Pousser vers Ghost après génération")
    args = parser.parse_args()

    date_pub = datetime.now().strftime("%d %B %Y, %Hh%M")

    # Mode push d'un brouillon existant
    if args.draft:
        with open(args.draft, "r", encoding="utf-8") as f:
            md = f.read()
        titre = md.splitlines()[0].lstrip("# ").strip()
        article = {"titre": titre, "resume": [], "categorie": args.category,
                   "nb_sources": 0, "corps": {}, "sources": []}
        push_to_ghost(article, md)
        return

    # Ingestion
    print("→ Ingestion du contenu source…")
    content = ingest_url(args.url) if args.url else ingest_text(args.input)

    # Génération
    print("→ Génération de l'article (Claude)…")
    article = generate_article(content, args.category)
    print(f"✓ Titre : {article['titre']}")

    # Mise en forme
    md       = render_markdown(article, date_pub)
    md_path  = save_markdown(md, article["titre"])

    # Push Ghost (optionnel)
    if args.push:
        print("→ Push vers Ghost CMS…")
        push_to_ghost(article, md)

    print("\nPipeline terminé.")


if __name__ == "__main__":
    main()
