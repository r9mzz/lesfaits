"""
Test comparatif A/B : modèles sur les mêmes sujets et sources réelles.

Le workflow doit être rouge si une comparaison n'a pas réellement abouti :
un test A/B marqué « succès » alors que les générations ont échoué — ou qu'un
seul modèle a été exécuté — est un faux signal opérationnel et éditorial.
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
    # ⚠ Ce garde-fou exigeait DEUX modèles, et son intention est juste : un « A/B »
    # à un seul modèle ne compare rien, et un run vert sans comparaison est
    # exactement le faux positif qu'il a été ajouté pour empêcher.
    #
    # Mais depuis le 17/08 il n'y a plus de témoin : Groq a retiré
    # llama-3.3-70b-versatile, et aucun modèle Groq survivant ne peut porter le
    # format long (plafond de 8 000 tokens par requête, mesuré). Exiger un
    # second modèle rendrait donc l'outil inutilisable au moment précis où il
    # sert — évaluer un fournisseur de remplacement.
    #
    # Un seul modèle est donc accepté, mais l'essai est nommé pour ce qu'il est :
    # une VÉRIFICATION, pas une comparaison. L'intention du garde-fou est
    # préservée ailleurs — un échec de génération fait toujours sortir en
    # code 1 (voir la fin de cette fonction).
    mode = "COMPARAISON A/B" if len(MODELES) >= 2 else "VÉRIFICATION d'un seul modèle"
    print(f"[MODE] {mode} — {', '.join(MODELES)}")
    if len(MODELES) < 2:
        print("       Aucun témoin : ce test dit si le modèle produit un article "
              "conforme, PAS s'il écrit mieux qu'un autre.")

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
                # Affichage détaillé : le premier essai Mistral (18/08) rendait
                # « corps: null », ce qui ne dit pas s'il manque vraiment ou si
                # le modèle l'a rangé sous une autre clé. Sans les clés brutes
                # et le compte de mots, impossible de trancher entre « le
                # fournisseur écrit mal » et « il ne respecte pas notre schéma
                # JSON » — deux problèmes très différents, l'un rédhibitoire,
                # l'autre réparable en une ligne de prompt.
                # Le 18/08, Mistral a rendu un JSON amputé de `corps` et de
                # `sources`. Sans le texte BRUT, on ne peut pas dire s'il a été
                # tronqué en transit, mal réparé par _reparer_json_tronque, ou
                # jamais écrit. On garde donc une trace du brut.
                _brut = res.get("brut") or ""
                if _brut:
                    print(f"[BRUT] {len(_brut)} caractères · début : {_brut[:120]!r}")
                    print(f"[BRUT] fin : {_brut[-160:]!r}")
                corps = art.get("corps") or {}
                mots = {k: len(str(v).split()) for k, v in corps.items()} if isinstance(corps, dict) else {}
                print(json.dumps({
                    "clés rendues": sorted(art.keys()),
                    "titre": art.get("titre"),
                    "angle_reponse": art.get("angle_reponse"),
                    "resume": art.get("resume"),
                    "mots par section": mots,
                    "mots corps total": sum(mots.values()),
                    "sources citées": len(art.get("sources") or []),
                }, ensure_ascii=False, indent=2))
                for _sec in ("faits", "contexte", "nuances"):
                    _t = (corps or {}).get(_sec) or ""
                    if _t:
                        print(f"\n--- {_sec.upper()} ({len(str(_t).split())} mots) ---\n{_t}")
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
