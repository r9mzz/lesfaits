#!/usr/bin/env python3
"""Combien de tokens Groq compte-t-il RÉELLEMENT dans nos prompts ?

Le pipeline estime la taille d'une requête en divisant les caractères par 3,3.
Ce ratio n'a jamais été vérifié. Les sondes du 18/08 montrent qu'il est faux :
Groq a répondu « Limit 8000, Requested 8204 » à une requête que notre formule
chiffrait à 12 000 — soit 45 % de surestimation.

L'enjeu n'est pas cosmétique. `_groq_call` calcule
`max_tokens = plafond − marge − estimation` : une estimation gonflée rend ce
calcul négatif et fait retomber la réservation sur son plancher de 200 tokens,
alors qu'il reste réellement de la place pour écrire. C'est le mécanisme de la
famine de complétion, mesuré le 15/08 et attribué à la mauvaise cause.

On ne remplace donc pas un chiffre approximatif par un autre : on construit les
VRAIS messages de `generate()` — pas un texte de remplissage, dont la
tokenisation n'a rien à voir — et on demande à Groq ce qu'il compte.

⚠ 65 s entre deux essais : le plafond est un DÉBIT par minute. Sans cette
attente, la sonde consomme le budget qu'elle mesure (erreur du 17/08, qui avait
« trouvé » un plafond de 2 500 qui n'était que le reliquat de sa propre minute).
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

MODELE = os.getenv("MODELE", "openai/gpt-oss-120b")
CLE = os.getenv("K1", "")
_RESUME = os.getenv("GITHUB_STEP_SUMMARY")


def dire(ligne):
    print(ligne, flush=True)
    if _RESUME:
        with open(_RESUME, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")


def messages_reels(n_sources, snippet, contenu, article_type="actu"):
    """Les messages que `generate()` construit vraiment, interceptés avant l'envoi."""
    vus = []

    def faux(api_key, msgs, max_tokens=3500):
        vus.append(msgs)
        raise RuntimeError("interception")

    vrai = P._groq_call
    P._groq_call = faux
    try:
        P.generate(
            "Le rapport publié mardi par l'institut détaille la hausse observée. " * (contenu // 66),
            "societe",
            [{"url": f"https://www.exemple-institution{i}.fr/publications/rapport-{i}",
              "title": f"Rapport annuel {i} sur l'évolution du secteur",
              "snippet": "L'organisme relève une progression de 3,2 % sur douze mois. " * (snippet // 58),
              "institution": f"Institut national {i}"}
             for i in range(n_sources)],
            article_type=article_type,
        )
    except Exception:
        pass
    finally:
        P._groq_call = vrai
    return vus[0] if vus else None


def compte_reel(msgs):
    """Ce que Groq compte. Accepté → usage.prompt_tokens ; refusé → « Requested N ».

    ⚠ On passe par la bibliothèque `groq` et non par un appel HTTP nu : un
    POST sans les en-têtes attendus est bloqué par Cloudflare en 403
    « error code: 1010 », et on mesure alors le pare-feu, pas le modèle.
    """
    from groq import Groq
    try:
        r = Groq(api_key=CLE).chat.completions.create(
            model=MODELE, max_tokens=1, messages=msgs)
        return r.usage.prompt_tokens, "accepté"
    except Exception as e:  # noqa: BLE001
        txt = str(e)
        m = re.search(r"Requested (\d+)", txt)
        if m:
            # « Requested » compte le prompt PLUS la réservation de sortie (1).
            return int(m.group(1)) - 1, "refusé (plafond)"
        return None, f"refusé — {txt[:130]}"


if not CLE:
    dire("GROQ_API_KEY absente")
    sys.exit(1)

dire(f"=== Ratio caractères/token RÉEL — modèle {MODELE} ===")
dire("")
dire(f"  {'config':<28}{'caract.':>9}{'estimé':>9}{'RÉEL':>8}{'car/tk':>8}  issue")

# ⚠ Les deux variantes « actu » d'une première version rendaient exactement le
# même prompt : la réservation d'écriture ramène déjà la matière à ses
# planchers dans les deux cas. On mesure donc ce qui part RÉELLEMENT, et on
# fait varier le nombre de sources pour obtenir plusieurs points de mesure.
CONFIGS = [
    ("brève 6 sources", 6, 380, 2500, "breve"),
    ("article 4 sources", 4, 950, 7000, "actu"),
    ("article 10 sources", 10, 950, 7000, "actu"),
]
ratios = []
for libelle, n, snip, clen, typ in CONFIGS:
    msgs = messages_reels(n, snip, clen, typ)
    if not msgs:
        dire(f"  {libelle:<28} prompt non construit")
        continue
    chars = sum(len(m.get("content", "")) for m in msgs)
    estime = int(chars / 3.3)
    reel, issue = compte_reel(msgs)
    if reel:
        ratios.append(chars / reel)
        dire(f"  {libelle:<28}{chars:>9}{estime:>9}{reel:>8}{chars/reel:>8.2f}  {issue}")
    else:
        dire(f"  {libelle:<28}{chars:>9}{estime:>9}{'?':>8}{'?':>8}  {issue}")
    time.sleep(65)

dire("")
if ratios:
    moy = sum(ratios) / len(ratios)
    dire(f"  Ratio moyen mesuré : {moy:.2f} caractères par token")
    dire(f"  Ratio utilisé par pipeline.py : 3.30  →  surestime de {100*(moy/3.3-1):.0f} %")
    dire("")
    dire("  ⚠ Prendre une valeur PRUDENTE (arrondie vers le bas) pour le correctif :")
    dire("  sous-estimer le prompt ferait réserver trop de sortie, donc un 413 certain.")
