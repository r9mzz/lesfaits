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

MODELE = os.getenv("MODELE_ESSAI", "").strip()

# ── LE MODÈLE DOIT ÊTRE NOMMÉ AVANT L'IMPORT, PAS APRÈS ────────────────────
# `p.GROQ_MODEL = MODELE` plus bas ne patche QUE la génération. La vérification
# résout son propre modèle À L'IMPORT, et sur un fournisseur autre que Groq ou
# Mistral elle ne peut rien deviner : depuis le 25/08 elle lève plutôt que de
# partir avec un nom d'un autre fournisseur (c'est ce qui envoyait
# `openai/gpt-oss-120b` à l'API de Google, et aurait produit un 404 par article
# en croyant que le fournisseur écrit mal).
#
# Ce garde-fou a fait exactement son travail sur l'essai Gemini du 26/08 — et
# il a arrêté l'essai, faute que ce fichier lui donne le nom assez tôt. On pose
# donc `GROQ_MODEL_OVERRIDE` AVANT l'import : la génération et la vérification
# lisent alors le même modèle, ce qui est précisément la propriété que le
# module partagé garantit.
if MODELE:
    os.environ.setdefault("GROQ_MODEL_OVERRIDE", MODELE)

import pipeline as p  # noqa: E402
NB_SUJETS = int(os.getenv("NB_SUJETS", "2"))


# Codes qui disent « le fournisseur n'a pas traité la demande », par opposition
# à « il l'a traitée et le résultat est mauvais ». Volontairement restreint aux
# refus d'ACCÈS : un 429 (débit) ou un 400 (requête trop grosse) sont des
# conditions d'exploitation qui, elles, méritent de compter comme un échec.
_CODES_PANNE_ACCES = ("401", "403", "404")


def _est_panne_acces(err: Exception) -> bool:
    """Le fournisseur a refusé l'accès — clé invalide, modèle hors palier,
    ou solde de compte à zéro.

    ⚠ TROU CORRIGÉ LE 30/08, dans ce correctif même. `QuotaJournalierEpuise`
    n'était pas reconnu : l'essai a donc de nouveau conclu « 3 sujet(s) sur 3
    n'ont pas produit d'article conforme » alors que toutes les clés étaient
    épuisées et qu'aucun appel n'avait abouti. Un solde à zéro n'a rien mesuré,
    exactement comme une clé invalide.

    Le bord reste le même : un 429 est une condition de DÉBIT — le fournisseur
    a accepté la clé et le modèle — et continue de compter comme un échec.
    """
    nom = type(err).__name__
    texte = f"{nom} {err}"
    if "Authentication" in nom or "NotFound" in nom or "Quota" in nom:
        return True
    if "Error code: 402" in texte or "solde épuisé" in texte.lower():
        return True
    return any(f"Error code: {c}" in texte for c in _CODES_PANNE_ACCES)


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
    pannes: list[str] = []
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
            # ⚠ 30/08 : UN REFUS D'ACCÈS N'EST PAS UN VERDICT ÉDITORIAL.
            # Un essai de `mistral-medium-latest` a présenté une clé Google —
            # trois `401 Invalid API Key` — et l'essai a conclu « 3 sujets sur
            # 3 n'ont pas produit d'article conforme ». Lu vite, ça dit « ce
            # modèle ne sait pas écrire » d'un modèle jamais interrogé. C'est
            # la même famille que le flux RSS qui répond 200 avec 0 article :
            # l'échec le plus coûteux est celui qui ressemble à un résultat.
            if _est_panne_acces(e):
                pannes.append(f"{type(e).__name__}: {str(e)[:200]}")
                print(f"[PANNE D'ACCÈS] {type(e).__name__}: {e}")
                print("               Ce n'est PAS un verdict sur la rédaction : "
                      "le fournisseur n'a jamais traité la demande.")
                continue
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
    # L'ORDRE COMPTE : une panne d'accès prime sur tout verdict éditorial. Si
    # le fournisseur n'a jamais traité la demande, l'essai n'a RIEN mesuré et
    # doit le dire — pas rendre un compte de sujets « non conformes ».
    if pannes:
        print(f"[PANNE D'ACCÈS] {len(pannes)} sujet(s) sur {len(sujets)} refusés "
              "par le fournisseur — AUCUNE mesure de rédaction n'a été faite.")
        # ⚠ NE PAS nommer cette variable `p` : `pipeline` est importé sous ce
        # nom, et une affectation locale dans `main()` le rend local pour TOUTE
        # la fonction — `p.GROQ_MODEL = MODELE`, cinquante lignes plus haut,
        # lève alors UnboundLocalError. C'est ce qui a cassé l'essai du 30/08,
        # dans le correctif même qui devait le fiabiliser.
        for _panne in pannes[:3]:
            print(f"                {_panne}")
        print("                Vérifier que la clé appartient au fournisseur "
              "essayé (entrée « cle » du workflow) et que le modèle est dans "
              "le palier de l'abonnement.")
        return 2
    if echecs:
        print(f"[ÉCHEC] {echecs} sujet(s) sur {len(sujets)} n'ont pas produit "
              "d'article conforme")
        return 1
    print(f"[OK] {len(sujets)} article(s) conformes au schéma et au plancher")
    return 0


if __name__ == "__main__":
    sys.exit(main())
