"""
Test comparatif A/B : modèles Groq sur les mêmes sujets et sources réelles.

Le workflow doit être rouge si une comparaison n'a pas réellement abouti :
un test A/B marqué « succès » alors que les générations ont échoué est un faux
signal opérationnel et éditorial.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pipeline as p

# Modèles à comparer — paramétrables depuis le workflow. La liste était codée
# en dur sur deux modèles Groq, dont `llama-3.3-70b-versatile` que Groq a retiré
# le 17/08 : l'outil ne pouvait donc plus rien comparer. Il sert désormais à
# répondre à la seule question qui reste ouverte sur un changement de
# fournisseur — celui-ci écrit-il aussi bien ? — et le prompt système, ses
# règles numérotées et la sortie JSON ont été calibrés deux mois sur Llama.
MODELES = [m.strip() for m in os.getenv(
    "MODELES_TEST", "llama-3.3-70b-versatile,openai/gpt-oss-120b").split(",") if m.strip()]
NB_SUJETS = 2


def collecter_sujets(n: int) -> list[dict]:
    """Réutilise la vraie collecte RSS + scoring du pipeline pour obtenir
    des sujets et des sources réelles du jour — pas des exemples inventés."""
    candidats = []
    published_topics = {a.get("titre", "") for a in p.load_index()[:140]}
    for src in p.RSS_SOURCES:
        items = p.fetch_rss(src)
        deja_vus = {i["id"] for i in candidats}
        for item in items:
            if item["id"] in deja_vus:
                continue
            scored = p.filtrer_et_classer([item], src["name"], published_topics, seuil_score=20)
            if scored:
                candidats.extend(scored)
        if len(candidats) >= n * 5:
            break
    candidats.sort(key=lambda x: x["_score"], reverse=True)
    return candidats[:n]


def generer_avec_modele(item: dict, modele: str) -> dict:
    p.GROQ_MODEL = modele
    cat = p.detect_category(item["content"])
    extra = p.duckduckgo_search(item["title"], max_results=8)
    try:
        art = p.generate(item["content"], cat, extra_sources=extra, rss_url=item.get("url"))
        return {"ok": True, "article": art}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {e}"}


def main() -> int:
    sujets = collecter_sujets(NB_SUJETS)
    print(f"\n{len(sujets)} sujet(s) sélectionné(s) pour le test\n{'='*70}")

    if not sujets:
        print("[ÉCHEC] aucun sujet sélectionné : comparaison impossible")
        return 1

    resultats = []
    echecs = 0
    for i, item in enumerate(sujets, 1):
        print(f"\n### SUJET {i} : {item['title'][:70]}\n")
        par_modele = {}
        for modele in MODELES:
            print(f"--- Génération avec {modele} ---")
            res = generer_avec_modele(item, modele)
            par_modele[modele] = res
            if res["ok"]:
                art = res["article"]
                print(json.dumps({
                    "titre": art.get("titre"),
                    "resume": art.get("resume"),
                    "corps": art.get("corps"),
                    "nb_sources": art.get("nb_sources"),
                }, ensure_ascii=False, indent=2))
            else:
                echecs += 1
                print(f"[ÉCHEC] {res['erreur']}")
            print()
        resultats.append({"sujet": item["title"], "resultats": par_modele})

    print("=" * 70)
    print(f"Test terminé — {len(resultats)} sujet(s) x {len(MODELES)} modèle(s)")
    if echecs:
        print(f"[ÉCHEC GLOBAL] {echecs} génération(s) sur {len(resultats) * len(MODELES)} ont échoué")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
