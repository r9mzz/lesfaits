"""Étape 5 — dry-run scraping (zéro génération, zéro coût API).
Pour 3 sujets de pile B, simule la recherche DDG + scraping du contenu
complet sur chaque source non protégée, et mesure :
- combien de sources donnent >= 1000 caractères de vrai contenu
- combien restent bloquées (protégées, paywall, timeout)
Aucune écriture disque, aucun appel de génération."""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline

SUJETS = [
    # (slug, titre) — 3 sujets choisis pour diversité thématique et sources attendues variées
    ("exoplanete-proche-terre-conditions-vie",
     "Exoplanète proche de la Terre aux conditions favorables à la vie"),
    ("loi-urgence-agricole-acetamipride",
     "Loi urgence agricole acétamipride France"),
    ("openai-reporte-introduction-bourse-2027",
     "OpenAI reporte introduction en bourse 2027"),
]


def run_sujet(slug, titre):
    print(f"\n{'='*90}")
    print(f"SUJET : {titre}")
    print(f"{'='*90}")

    extra = pipeline.duckduckgo_search(titre, max_results=8)
    pubmed = pipeline.pubmed_search(titre, max_results=4)
    seen = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen:
            extra.append(p); seen.add(p["url"])

    print(f"  Sources trouvées DDG+PubMed : {len(extra)}")

    resultats = []
    for src in extra:
        url = src["url"]
        domain = (urlparse(url).hostname or "").replace("www.", "")
        protege = pipeline._est_presse_protegee(url)

        if protege:
            resultats.append({"url": url, "domain": domain, "status": "protégé", "chars": 0,
                               "snippet_chars": len(src.get("snippet", ""))})
            print(f"  [PROTÉGÉ]  {domain:35s} snippet={len(src.get('snippet',''))}")
            continue

        t0 = time.time()
        try:
            full = pipeline.fetch_full_content(url)
            elapsed = time.time() - t0
            chars = len(full)
            status = "ok" if chars >= 1000 else ("partiel" if chars >= 500 else "vide")
            print(f"  [{status.upper():7s}]  {domain:35s} {chars:6d} car.  ({elapsed:.1f}s)")
            resultats.append({"url": url, "domain": domain, "status": status, "chars": chars,
                               "snippet_chars": len(src.get("snippet", ""))})
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  [ERREUR]   {domain:35s} {type(e).__name__}: {str(e)[:60]}  ({elapsed:.1f}s)")
            resultats.append({"url": url, "domain": domain, "status": "erreur", "chars": 0,
                               "snippet_chars": len(src.get("snippet", ""))})

    # Statistiques
    n_ok   = sum(1 for r in resultats if r["status"] == "ok")
    n_part = sum(1 for r in resultats if r["status"] == "partiel")
    n_prot = sum(1 for r in resultats if r["status"] == "protégé")
    n_vide = sum(1 for r in resultats if r["status"] in ("vide", "erreur"))
    total  = len(resultats)
    print(f"\n  RÉSUMÉ : {total} sources | ok(≥1000)={n_ok} | partiel(500-999)={n_part} | "
          f"protégé={n_prot} | vide/erreur={n_vide}")
    pct_utiles = round(100 * (n_ok + n_part) / max(total, 1))
    print(f"  Sources scrapées avec contenu ≥500 car : {n_ok+n_part}/{total} ({pct_utiles}%)")
    return n_ok, n_part, n_prot, n_vide, total


def main():
    print("DRY-RUN SCRAPING — aucune génération, aucun coût")
    print("Critère de succès : ≥50% des sources non-protégées donnent ≥1000 chars")
    totaux = {"ok": 0, "part": 0, "prot": 0, "vide": 0, "total": 0}
    for slug, titre in SUJETS:
        ok, part, prot, vide, total = run_sujet(slug, titre)
        totaux["ok"] += ok; totaux["part"] += part
        totaux["prot"] += prot; totaux["vide"] += vide; totaux["total"] += total

    print(f"\n{'='*90}")
    print("TOTAL TOUS SUJETS")
    print(f"{'='*90}")
    non_prot = totaux["total"] - totaux["prot"]
    utiles = totaux["ok"] + totaux["part"]
    pct = round(100 * utiles / max(non_prot, 1))
    print(f"  Sources non protégées : {non_prot}")
    print(f"  Avec ≥1000 chars (ok)  : {totaux['ok']}")
    print(f"  Avec 500-999 chars     : {totaux['part']}")
    print(f"  Vide/erreur            : {totaux['vide']}")
    print(f"  Taux utiles (≥500)     : {pct}%")
    if pct >= 50:
        print("\n  ✓ CRITÈRE ATTEINT — passage à l'étape 6 (génération) justifié")
    else:
        print("\n  ✗ CRITÈRE NON ATTEINT — le fix de scraping apporte peu sur ces sujets")


if __name__ == "__main__":
    main()
