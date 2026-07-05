"""
Test detecter() sur les 3 articles publiés le 03/07 (avant activation vérif).
Reconstruit les dicts article depuis le HTML, appelle detecter() sur chacun,
puis rejoue le test sur chaque version intermédiaire du vérificateur (commits
de la nuit 03→04/07).

Usage : python scripts/test_articles_03juillet.py
"""
import sys, os, re, json, subprocess
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)


# ── Parsing HTML → dict article ───────────────────────────────────────────────

def parse_article_html(slug: str) -> dict:
    html = (ROOT / "articles" / f"{slug}.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    titre = soup.find("h1", class_="art__title")
    titre = titre.get_text(strip=True) if titre else slug

    resume_el = soup.find("p", class_="art__resume")
    resume_txt = resume_el.get_text(" ", strip=True) if resume_el else ""
    # Découper en phrases pour correspondre au format attendu par le vérificateur
    resume = [s.strip() for s in re.split(r"(?<=[.!?])\s+", resume_txt) if s.strip()]

    corps = {"faits": "", "contexte": "", "nuances": ""}
    for h2 in soup.find_all("h2", class_="art__h2"):
        titre_section = h2.get_text(strip=True).lower()
        p = h2.find_next_sibling("p")
        texte = p.get_text(" ", strip=True) if p else ""
        if "fait" in titre_section:
            corps["faits"] = texte
        elif "contexte" in titre_section:
            corps["contexte"] = texte
        elif "nuance" in titre_section or "débat" in titre_section:
            corps["nuances"] = texte

    sources = []
    for li in soup.select("section.sources ol li"):
        cite = li.find("cite")
        em = li.find("em")
        a = li.find("a")
        if cite and a:
            sources.append({
                "institution": cite.get_text(strip=True),
                "titre": em.get_text(strip=True) if em else "",
                "url": a.get("href", ""),
            })

    return {
        "slug": slug,
        "titre": titre,
        "resume": resume,
        "corps": corps,
        "sources": sources,
        "nb_sources": len(sources),
    }


# ── Test principal ─────────────────────────────────────────────────────────────

TARGETS = [
    "exoplanete-proche-terre-conditions-vie",
    "accident-jean-pierre-raffarin-paris",
    "mousses-champignons-symbiose-inattendue",
]

# Commits de la nuit 03→04/07 qui touchent verification.py, du plus ancien au plus récent
COMMITS_VERIF = [
    ("5f141f9", "Active la vérification éditoriale Anthropic"),
    ("c186fd4", "Implémente la charte critères premium"),
    ("ff08eb9", "Rend la conformité atteignable"),
    ("927d02e", "Deux corrections (compteur_incoherent + sujet_sensible)"),
    ("84e750f", "Garde-fou perte de substance"),
    # HEAD = état actuel
]

def run_detecter_on_commit(art: dict, commit: str | None = None) -> dict:
    """
    Exécute detecter() avec la version de verification.py au commit donné.
    Si commit=None, utilise la version courante.
    """
    if commit:
        # Restaurer verification.py au commit demandé
        content = subprocess.check_output(
            ["git", "show", f"{commit}:scripts/verification.py"],
            cwd=str(ROOT)
        )
        tmp = ROOT / "scripts" / "verification_tmp.py"
        tmp.write_bytes(content)
        # Import dynamique
        import importlib.util
        spec = importlib.util.spec_from_file_location("verification_tmp", tmp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        detect_fn = mod.detecter
        # Les vieilles versions n'ont pas forcément _problemes_bloquants
        bloquants_fn = getattr(mod, "_problemes_bloquants", None)
    else:
        from verification import detecter as detect_fn
        bloquants_fn = None

    # Définition inline si absente dans la version testée
    def _bloquants(problemes):
        if bloquants_fn:
            return bloquants_fn(problemes)
        return [p for p in problemes if p.get("bloc") in (1, 2, 5)]

    try:
        rapport = detect_fn(art)
        problemes = rapport.get("problemes", [])
        bloquants = _bloquants(problemes)
        return {
            "conforme": rapport.get("conforme", False),
            "sujet_sensible": rapport.get("sujet_sensible", False),
            "sujet_sensible_raison": rapport.get("sujet_sensible_raison", ""),
            "total": len(problemes),
            "bloquants": len(bloquants),
            "par_bloc": {str(b): sum(1 for p in problemes if p.get("bloc") == b) for b in (1,2,3,4,5)},
        }
    except Exception as e:
        return {"erreur": str(e)}


def main():
    print("\n" + "=" * 72)
    print("TEST DETECTER() — 3 articles publiés le 03/07 (avant vérification)")
    print("=" * 72)

    # Phase 1 : test avec l'état actuel du vérificateur
    print("\n── PHASE 1 : état actuel (HEAD) ──\n")
    articles = {}
    for slug in TARGETS:
        art = parse_article_html(slug)
        articles[slug] = art
        print(f"[{slug}]")
        print(f"  Titre   : {art['titre'][:65]}")
        print(f"  Sources : {len(art['sources'])}")
        res = run_detecter_on_commit(art, commit=None)
        if "erreur" in res:
            print(f"  ERREUR  : {res['erreur']}")
        else:
            verdict = "CONFORME" if res["conforme"] else ("SENSIBLE" if res["sujet_sensible"] else f"NON CONFORME — {res['bloquants']} bloquant(s)")
            print(f"  Verdict : {verdict}")
            print(f"  Total pb: {res['total']}  |  Bloquants: {res['bloquants']}")
            print(f"  Par bloc: {res['par_bloc']}")
            if res["sujet_sensible"]:
                print(f"  Raison  : {res['sujet_sensible_raison'][:80]}")
        print()

    # Phase 2 : bisection — quel commit a fait basculer le résultat ?
    print("\n── PHASE 2 : bisection par commit de la nuit 03→04/07 ──\n")

    # Vérifier si le commit existe ET touche verification.py
    valid_commits = []
    for commit, label in COMMITS_VERIF:
        try:
            files = subprocess.check_output(
                ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit],
                cwd=str(ROOT)
            ).decode()
            if "verification.py" in files:
                valid_commits.append((commit, label))
            else:
                print(f"  [{commit[:7]}] {label} — ne touche pas verification.py, ignoré")
        except Exception as e:
            print(f"  [{commit[:7]}] inaccessible : {e}")

    if not valid_commits:
        print("  Aucun commit valide avec verification.py trouvé — bisection impossible")
        return

    print(f"  {len(valid_commits)} commit(s) à tester sur verification.py\n")

    for slug in TARGETS:
        art = articles[slug]
        print(f"\n  [{slug[:45]}]")
        for commit, label in valid_commits:
            res = run_detecter_on_commit(art, commit=commit)
            if "erreur" in res:
                verdict = f"ERREUR: {res['erreur'][:60]}"
            elif res.get("conforme"):
                verdict = "CONFORME ✓"
            elif res.get("sujet_sensible"):
                verdict = f"SENSIBLE"
            else:
                verdict = f"NON CONFORME — {res['bloquants']} bloquant(s) / {res['total']} total"
            print(f"    {commit[:7]} {label[:45]:45s} → {verdict}")

    # Nettoyage
    tmp = ROOT / "scripts" / "verification_tmp.py"
    if tmp.exists():
        tmp.unlink()

    print("\n" + "=" * 72)
    print("Terminé.")


if __name__ == "__main__":
    main()
