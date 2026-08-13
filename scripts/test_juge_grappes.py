# -*- coding: utf-8 -*-
"""BACKTEST — un petit modèle sait-il dire que deux titres parlent du même fait ?

Notre regroupement compare les mots des titres, tronqués à 8 caractères. C'est
grossier et documenté comme provisoire : « antillais » ne rejoint pas
« antilles » (ils diffèrent à la 8e lettre), la grappe « éclipse solaire »
mélange 30 articles d'angles différents, et le regroupement par composantes
connexes fabriquait des paquets de 59 articles sans rapport avant correction.

« Ces deux titres parlent-ils du même événement ? » est une question FERMÉE et
FACTUELLE — la famille où le juge de sources a réussi (12/08), et non celle du
juge de sujet, qui demandait un avis éditorial et s'est écrasé à 50 %.

DEUX ÉPREUVES :

  A — FAUX POSITIFS, sur une référence non circulaire. Deux titres tirés au
      hasard dans le journal de veille ne décrivent quasiment jamais le même
      événement : c'est un « NON » objectif, qui ne doit rien à notre
      algorithme. Un juge qui répond OUI ici fusionnerait n'importe quoi.

  B — NOTRE REGROUPEMENT ACTUEL, passé au crible. On tire des paires DANS une
      même grappe existante. Chaque « NON » du juge est un défaut probable de
      notre méthode — c'est la mesure de notre taux de blobs, et elle vaut
      autant que le score du juge.

⚠ Le juge ne voit que deux titres. Il ne télécharge rien, ne voit ni la date
ni le flux d'origine.

⚠ Ne tourne pas dans le sandbox (api.groq.com injoignable). Lancer via
.github/workflows/juge_grappes.yml.

    python scripts/test_juge_grappes.py --limite 30
"""
import argparse
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
import veille as V  # noqa: E402

MODELE = os.getenv("JUGE_MODELE", "llama-3.1-8b-instant")

PROMPT = """Tu compares deux titres d'articles de presse.

Question unique : décrivent-ils le MÊME ÉVÉNEMENT — le même fait, la même
décision, la même étude, le même incident ?

Réponds OUI seulement si les deux titres portent sur le même fait précis, même
s'ils l'abordent sous un angle différent ou avec des mots différents.

Réponds NON s'ils portent sur des faits distincts, même proches : deux
événements du même thème, deux épisodes différents, ou un fait et son
commentaire général.

Un seul mot : OUI ou NON."""


def juger(client, t1: str, t2: str) -> str | None:
    for tentative in range(4):
        try:
            r = client.chat.completions.create(
                model=MODELE,
                messages=[{"role": "system", "content": PROMPT},
                          {"role": "user", "content": f"TITRE 1 : {t1}\nTITRE 2 : {t2}"}],
                temperature=0, max_tokens=4)
            mot = (r.choices[0].message.content or "").strip().upper()
            if mot.startswith("OUI"):
                return "OUI"
            if mot.startswith("NON"):
                return "NON"
            return None
        except Exception as e:  # noqa: BLE001
            if "rate" in str(e).lower() or "429" in str(e):
                time.sleep(20 * (tentative + 1))
                continue
            print(f"    erreur : {type(e).__name__} {str(e)[:110]}")
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=30, help="paires par épreuve")
    args = ap.parse_args()

    items = V.charger().get("items", {})
    if len(items) < 50:
        print("Journal de veille trop maigre — lancer d'abord des passages.")
        return 1
    print(f"{len(items)} items dans le journal de veille\n")

    try:
        from groq import Groq
    except ImportError:
        print("ERREUR : paquet groq absent.")
        return 1
    if not os.getenv("GROQ_API_KEY"):
        print("ERREUR : GROQ_API_KEY absent — lancer depuis le runner GitHub.")
        return 1
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    grappes = V._grouper_membres(items)
    random.seed(13)

    # ── ÉPREUVE A — faux positifs ────────────────────────────────────────────
    cles = list(items)
    paires_hasard = []
    while len(paires_hasard) < args.limite:
        a, b = random.sample(cles, 2)
        ta, tb = items[a].get("titre", ""), items[b].get("titre", "")
        if ta and tb and ta != tb:
            paires_hasard.append((ta, tb))

    print(f"ÉPREUVE A — {len(paires_hasard)} paires au hasard, modèle {MODELE}")
    print("  Attendu : NON presque partout (deux titres au hasard sur 2 000)\n")
    ca = Counter()
    faux_oui = []
    for t1, t2 in paires_hasard:
        v = juger(client, t1, t2)
        ca[v or "—"] += 1
        if v == "OUI":
            faux_oui.append((t1, t2))
    n = sum(v for k, v in ca.items() if k in ("OUI", "NON")) or 1
    print(f"  NON : {ca['NON']}/{n} ({100 * ca['NON'] / n:.0f} %)   "
          f"OUI : {ca['OUI']}   sans verdict : {ca['—']}")
    if faux_oui:
        print("\n  Paires que le juge a fusionnées à tort :")
        for t1, t2 in faux_oui[:5]:
            print(f"    · {t1[:58]}\n      {t2[:58]}")

    # ── ÉPREUVE B — notre regroupement au crible ─────────────────────────────
    multi = [m for m in grappes.values() if len(m) >= 2]
    paires_grappe = []
    for m in random.sample(multi, min(args.limite, len(multi))):
        a, b = random.sample(m, 2)
        ta, tb = items[a].get("titre", ""), items[b].get("titre", "")
        if ta and tb and ta != tb:
            paires_grappe.append((ta, tb))

    print(f"\nÉPREUVE B — {len(paires_grappe)} paires prises DANS nos grappes")
    print("  Chaque NON est un défaut probable de NOTRE regroupement,")
    print("  pas une erreur du juge — c'est la mesure qui nous intéresse.\n")
    cb = Counter()
    desaccords = []
    for t1, t2 in paires_grappe:
        v = juger(client, t1, t2)
        cb[v or "—"] += 1
        if v == "NON":
            desaccords.append((t1, t2))
    nb = sum(v for k, v in cb.items() if k in ("OUI", "NON")) or 1
    print(f"  OUI (regroupement confirmé) : {cb['OUI']}/{nb} ({100 * cb['OUI'] / nb:.0f} %)")
    print(f"  NON (blob probable)         : {cb['NON']}/{nb} ({100 * cb['NON'] / nb:.0f} %)")
    if desaccords:
        print("\n  Paires que NOUS avons regroupées et que le juge sépare :")
        for t1, t2 in desaccords[:8]:
            print(f"    · {t1[:58]}\n      {t2[:58]}")

    # ── ÉPREUVE C — cas connus ───────────────────────────────────────────────
    print("\nÉPREUVE C — cas dont on connaît déjà la réponse")
    connus = [
        ("Chlordécone : huit adultes antillais sur dix en portent dans le sang",
         "Chlordécone dans le sang : les Antilles largement contaminées",
         "OUI", "notre troncature à 8 caractères les sépare à tort"),
        ("Canadair : la flotte française sera remplacée en 2027",
         "Palantir remplace son directeur technique",
         "NON", "faux positif historique du filtre anti-doublon"),
        ("Éclipse solaire : les plus beaux soleils noirs du jeu vidéo",
         "Éclipse solaire : tout ce qu'il faut faire pour observer le phénomène",
         "NON", "deux angles distincts, aujourd'hui dans la même grappe"),
    ]
    for t1, t2, attendu, note in connus:
        v = juger(client, t1, t2) or "—"
        marque = "✓" if v == attendu else "✗"
        print(f"  {marque} attendu {attendu}, obtenu {v:<3} — {note}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
