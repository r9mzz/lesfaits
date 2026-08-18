#!/usr/bin/env python3
"""Essai d'UN fournisseur sur des sujets réels — pas un comparatif A/B.

Pourquoi un outil séparé : `test_model_compare.py` exige deux modèles, et il a
raison. Un comparatif à un seul modèle ne compare rien, et un run vert sans
comparaison est un faux positif — c'est le garde-fou rétabli le 18/08, à ne pas
contourner.

Mais depuis que Groq a retiré `llama-3.3-70b-versatile`, il n'existe plus de
témoin, et la question posée n'est plus « lequel écrit le mieux ? » mais
« ce fournisseur produit-il un article conforme à notre schéma ? ». C'est une
VÉRIFICATION, elle mérite son propre outil et son propre nom.

N'écrit rien en production : ni `articles/`, ni `data/`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline as p  # noqa: E402

MODELE = os.getenv("MODELE_ESSAI", "").strip()
NB_SUJETS = int(os.getenv("NB_SUJETS", "2"))


def main() -> int:
    if not MODELE:
        print("[ÉCHEC] MODELE_ESSAI non défini")
        return 1
    p.GROQ_MODEL = MODELE
    print(f"[ESSAI] fournisseur {p.LLM_BASE_URL or 'Groq (défaut)'} · modèle {MODELE}")
    print("        Vérification d'un seul modèle : dit si l'article est CONFORME,")
    print("        pas s'il est meilleur qu'un autre — il n'y a plus de témoin.\n")

    from test_model_compare import collecter_sujets
    sujets = collecter_sujets(NB_SUJETS)
    if not sujets:
        print("[ÉCHEC] aucun sujet collecté")
        return 1

    echecs = 0
    for i, item in enumerate(sujets, 1):
        print("=" * 74)
        print(f"SUJET {i} : {item['title'][:70]}")
        print("=" * 74)
        cat = p.detect_category(item["content"])
        extra = p.duckduckgo_search(item["title"], max_results=8)
        brut = {}
        vrai = p._groq_call

        def _capture(*a, **kw):
            r = vrai(*a, **kw)
            brut["texte"] = r
            return r

        p._groq_call = _capture
        try:
            art = p.generate(item["content"], cat, extra_sources=extra,
                             rss_url=item.get("url"))
        except Exception as e:  # noqa: BLE001
            print(f"[ÉCHEC] {type(e).__name__}: {e}")
            t = brut.get("texte", "")
            if t:
                print(f"[BRUT] {len(t)} car. · fin : {t[-200:]!r}")
            echecs += 1
            continue
        finally:
            p._groq_call = vrai

        corps = art.get("corps") or {}
        # ⚠ Le corps peut manquer alors que la génération a « réussi » : le JSON
        # est alors mal lu, pas mal écrit, et l'erreur est silencieuse. Sans la
        # réponse BRUTE on ne peut que supposer — ce qui a déjà coûté deux
        # diagnostics faux cette semaine. On l'affiche donc dès que le corps
        # manque, en montrant la zone de rupture plutôt que le début du texte.
        if not corps:
            t = brut.get("texte", "")
            print(f"[BRUT] {len(t)} caractères — corps absent, voici le texte réel :")
            import re as _re
            m = _re.search(r'"corps"', t)
            if m:
                print(f"[BRUT] zone « corps » : {t[m.start():m.start() + 700]!r}")
            else:
                print(f"[BRUT] aucune clé \"corps\" dans la réponse. Fin : {t[-500:]!r}")
        mots = {k: len(str(v).split()) for k, v in corps.items()}
        total = sum(mots.values())
        print(json.dumps({
            "titre": art.get("titre"),
            "angle_reponse": art.get("angle_reponse"),
            "mots par section": mots,
            "mots total": total,
            "sources citées": len(art.get("sources") or []),
            "clés manquantes": [k for k in ("corps", "sources", "resume", "titre")
                                if not art.get(k)],
        }, ensure_ascii=False, indent=2))

        print(f"\n### {art.get('titre')}\n")
        for ph in art.get("resume") or []:
            print(f"  {ph}")
        for sec, titre in (("faits", art.get("titre_faits") or "Les faits"),
                           ("contexte", art.get("titre_contexte") or "Contexte"),
                           ("nuances", art.get("titre_nuances") or "Débats et nuances")):
            txt = corps.get(sec) or ""
            if txt:
                print(f"\n--- {titre} ({len(str(txt).split())} mots) ---\n{txt}")
        print("\n--- SOURCES ---")
        for n, s in enumerate(art.get("sources") or [], 1):
            print(f"  [{n}] {s.get('titre') or s.get('title') or '?'} — {s.get('url','')}")
        # Le plancher qui rejette réellement, pour situer sans avoir à le chercher.
        plancher = p.SEUILS_FORMAT["article"]["plancher"]
        print(f"\n[VERDICT] {total} mots (plancher de publication : {plancher}) · "
              f"{len(art.get('sources') or [])} source(s)")
        if total < plancher:
            echecs += 1
        print()

    print("=" * 74)
    if echecs:
        print(f"[ÉCHEC] {echecs} sujet(s) sur {len(sujets)} n'ont pas produit "
              "d'article conforme")
        return 1
    print(f"[OK] {len(sujets)} article(s) conformes au schéma et au plancher")
    return 0


if __name__ == "__main__":
    sys.exit(main())
