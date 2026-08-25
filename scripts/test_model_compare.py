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
from fenetres_modeles import _TPM_PAR_MODELE_GEN

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
    """Génère, et CAPTURE la réponse brute du modèle."""
    p.GROQ_MODEL = modele
    brut = {}
    _vrai = p._groq_call

    def _capture(*a, **kw):
        r = _vrai(*a, **kw)
        brut["texte"] = r
        return r

    p._groq_call = _capture
    cat = p.detect_category(item["content"])
    extra = p.duckduckgo_search(item["title"], max_results=8)
    try:
        art = p.generate(item["content"], cat, extra_sources=extra, rss_url=item.get("url"))
        return {"ok": True, "article": art, "brut": brut.get("texte", "")}
    except Exception as e:
        return {"ok": False, "erreur": f"{type(e).__name__}: {e}",
                "brut": brut.get("texte", "")}
    finally:
        p._groq_call = _vrai


def main() -> int:
    # Un comparatif A/B n'a de sens qu'avec au moins deux modèles. Un run à un
    # seul modèle peut être utile comme diagnostic fournisseur, mais il ne doit
    # pas emprunter ce workflow ni pouvoir rendre ce comparatif vert.
    if len(MODELES) < 2:
        print(
            f"[ÉCHEC] comparaison A/B impossible : {len(MODELES)} modèle(s) configuré(s), "
            "il en faut au moins deux"
        )
        return 1

    # Le budget de fenêtre modifie directement la quantité de sources injectée
    # au rédacteur. Comparer un modèle avec une valeur supposée — ou avec le
    # fallback historique de 12 000 — fausse donc le verdict éditorial. Le banc
    # A/B est volontairement fail-closed : chaque modèle testé doit avoir une
    # fenêtre mesurée/vérifiée dans la table partagée avant toute collecte.
    sans_fenetre_verifiee = [m for m in MODELES if m not in _TPM_PAR_MODELE_GEN]
    if sans_fenetre_verifiee:
        print(
            "[ÉCHEC] comparaison A/B impossible : fenêtre TPM non vérifiée pour "
            + ", ".join(sans_fenetre_verifiee)
            + ". Mesurer le plafond fournisseur avant de lancer le comparatif."
        )
        return 1

    print(f"[MODE] COMPARAISON A/B — {', '.join(MODELES)}")
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
