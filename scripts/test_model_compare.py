"""
Test comparatif A/B (21/07) : llama-3.3-70b-versatile vs openai/gpt-oss-120b.

Objectif : le second modèle offre 200K tokens/jour par clé contre 100K pour
le premier — un doublement de capacité gratuit SI la qualité tient. Ce
script génère les MÊMES sujets, avec les MÊMES sources réelles, une fois
par modèle, pour une comparaison équitable. Ne touche à aucun fichier de
production (n'écrit rien dans articles/ ni data/) — sortie en JSON sur
stdout pour copier-coller vers une revue externe (ChatGPT ou autre).

Usage : python scripts/test_model_compare.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pipeline as p

MODELES = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]
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
        if len(candidats) >= n * 5:  # assez de matière pour choisir les meilleurs
            break
    candidats.sort(key=lambda x: x["_score"], reverse=True)
    return candidats[:n]


def generer_avec_modele(item: dict, modele: str) -> dict:
    p.GROQ_MODEL = modele  # override direct de la constante module
    cat = p.detect_category(item["content"])
    extra = p.duckduckgo_search(item["title"], max_results=8)
    try:
        art = p.generate(item["content"], cat, extra_sources=extra, rss_url=item.get("url"))
        return {"ok": True, "article": art}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {e}"}


def main():
    sujets = collecter_sujets(NB_SUJETS)
    print(f"\n{len(sujets)} sujet(s) sélectionné(s) pour le test\n{'='*70}")

    resultats = []
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
                print(f"[ÉCHEC] {res['erreur']}")
            print()
        resultats.append({"sujet": item["title"], "resultats": par_modele})

    print("=" * 70)
    print(f"Test terminé — {len(resultats)} sujet(s) x {len(MODELES)} modèle(s)")


if __name__ == "__main__":
    main()
