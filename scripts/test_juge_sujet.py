# -*- coding: utf-8 -*-
"""BACKTEST — un petit modèle peut-il écarter un sujet creux AVANT de l'écrire ?

Question posée par Nahil le 12/08 : peut-on tester l'idée sans payer Groq ?
Oui, et mieux qu'un simple essai — on dispose de la bonne réponse.

`data/verification_log.json` contient 382 vérifications dont l'issue est
connue. Deux classes exploitables :

    angle_insuffisant = True              → le sujet était creux  (112)
    corrige_automatiquement / conforme    → le sujet tenait       (108)

Ces étiquettes ont été posées par le fact-checker APRÈS génération complète,
c'est-à-dire après ~35 000 jetons dépensés par sujet. La question est de
savoir si un petit modèle, en une question fermée sur le seul titre, aurait
pu rendre le même verdict pour cinquante fois moins cher.

CE QUI SE JOUE : 64 % de nos rejets qualité sont des `angle_insuffisant`. Si
ce juge fonctionne, il supprime la majorité des générations inutiles. S'il se
trompe souvent, il tue de bons articles — et c'est la mesure qui le dira, pas
l'intuition.

⚠ LIMITE ASSUMÉE : le juge ne voit ici que le TITRE (reconstitué depuis le
slug). Le vrai juge, en production, verrait aussi l'extrait RSS et les
sources trouvées. Ce test est donc un PLANCHER : ce qu'on mesure ici ne peut
que s'améliorer avec plus de contexte. Un mauvais résultat ne condamne pas
l'idée ; un bon résultat la valide largement.

⚠ Ne tourne pas dans le sandbox de développement (api.groq.com injoignable).
À lancer depuis le runner GitHub via .github/workflows/juge_sujet.yml.

    python scripts/test_juge_sujet.py --limite 60
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RACINE = Path(__file__).resolve().parent.parent
JOURNAL = RACINE / "data" / "verification_log.json"

# Petit modèle : la question est fermée, elle ne demande pas le modèle qui
# rédige. C'est tout l'intérêt — un juge doit coûter une fraction d'un article,
# sinon il ne se paie jamais.
MODELE = os.getenv("JUGE_MODELE", "llama-3.1-8b-instant")

PROMPT = """Tu es chef d'édition d'un journal d'actualité factuel.

On te donne le TITRE d'un sujet candidat. Tu dois dire s'il mérite un article
de 500 mots, en te fondant sur une seule question : ce titre annonce-t-il un
ÉVÉNEMENT DATÉ, un RÉSULTAT CHIFFRÉ ou une DÉCISION identifiable, sur lequel
on pourra écrire des faits précis ?

Réponds PUBLIABLE si le titre annonce un fait vérifiable et daté.
Réponds CREUX si le titre est une généralité, un marronnier, un conseil
pratique, une tendance sans événement, une question ouverte, ou s'il faudrait
inventer du contexte pour remplir l'article.

Réponds par UN SEUL MOT : PUBLIABLE ou CREUX."""


def titre_depuis_slug(slug: str) -> str:
    """Le journal ne conserve pas le titre, seulement le slug. Il en est une
    approximation lisible — accents et ponctuation perdus, mots conservés."""
    return re.sub(r"[-_]+", " ", slug).strip().capitalize()


def charger_jeu() -> list[tuple[str, bool]]:
    """(titre, creux) — `creux=True` quand le fact-checker a conclu au sujet
    insuffisant après génération complète."""
    entrees = json.loads(JOURNAL.read_text(encoding="utf-8"))
    if isinstance(entrees, dict):
        entrees = entrees.get("entrees", [])
    jeu, vus = [], set()
    for e in entrees:
        slug = e.get("slug") or ""
        statut = e.get("statut") or ""
        if not slug or slug in vus:
            continue
        if e.get("angle_insuffisant"):
            creux = True
        elif statut in ("corrige_automatiquement", "conforme_du_premier_coup"):
            creux = False
        else:
            # rejete_sensible (motif LÉGAL, pas éditorial), erreur technique,
            # rejet pour un autre défaut : l'étiquette ne dit rien du SUJET,
            # on les écarte plutôt que de les compter au hasard.
            continue
        vus.add(slug)
        jeu.append((titre_depuis_slug(slug), creux))
    return jeu


def juger(client, titre: str) -> str | None:
    for tentative in range(4):
        try:
            r = client.chat.completions.create(
                model=MODELE,
                messages=[{"role": "system", "content": PROMPT},
                          {"role": "user", "content": f"TITRE : {titre}"}],
                temperature=0,
                max_tokens=6,
            )
            mot = (r.choices[0].message.content or "").strip().upper()
            if "CREUX" in mot:
                return "CREUX"
            if "PUBLIABLE" in mot:
                return "PUBLIABLE"
            return None
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "rate" in msg.lower() or "429" in msg:
                attente = 20 * (tentative + 1)
                print(f"    limite atteinte, pause {attente}s")
                time.sleep(attente)
                continue
            print(f"    erreur : {type(e).__name__} {msg[:120]}")
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=60,
                    help="nombre de sujets à juger (bornes le coût en jetons)")
    args = ap.parse_args()

    jeu = charger_jeu()
    creux = [x for x in jeu if x[1]]
    bons = [x for x in jeu if not x[1]]
    print(f"Jeu étiqueté disponible : {len(creux)} sujets creux, {len(bons)} sujets tenus\n")

    # Échantillon ÉQUILIBRÉ : sur un jeu déséquilibré, un juge qui répond
    # toujours la classe majoritaire obtiendrait un bon score sans rien savoir.
    random.seed(12)
    n = min(args.limite // 2, len(creux), len(bons))
    echantillon = random.sample(creux, n) + random.sample(bons, n)
    random.shuffle(echantillon)
    print(f"Échantillon jugé : {2 * n} sujets ({n} de chaque classe), modèle {MODELE}\n")

    try:
        from groq import Groq
    except ImportError:
        print("ERREUR : paquet groq absent.")
        return 1
    cle = os.getenv("GROQ_API_KEY", "")
    if not cle:
        print("ERREUR : GROQ_API_KEY absent — ce test doit tourner sur le runner GitHub.")
        return 1
    client = Groq(api_key=cle)

    vp = vn = fp = fn = indecis = 0
    erreurs_couteuses, erreurs_manquees = [], []
    for i, (titre, est_creux) in enumerate(echantillon, 1):
        verdict = juger(client, titre)
        if verdict is None:
            indecis += 1
            continue
        predit_creux = verdict == "CREUX"
        if est_creux and predit_creux:
            vp += 1
        elif not est_creux and not predit_creux:
            vn += 1
        elif not est_creux and predit_creux:
            fp += 1
            erreurs_couteuses.append(titre)
        else:
            fn += 1
            erreurs_manquees.append(titre)
        if i % 10 == 0:
            print(f"  {i}/{len(echantillon)} jugés")

    juges = vp + vn + fp + fn
    if not juges:
        print("\nAucun verdict exploitable.")
        return 1

    print("\n" + "=" * 68)
    print(f"RÉSULTAT sur {juges} sujets ({indecis} sans verdict exploitable)")
    print("=" * 68)
    print(f"  sujets creux correctement écartés     : {vp:>3} / {vp + fn}")
    print(f"  sujets valables correctement gardés   : {vn:>3} / {vn + fp}")
    print(f"  ⚠ BONS ARTICLES TUÉS À TORT           : {fp:>3}  ({100 * fp / max(vn + fp, 1):.0f} %)")
    print(f"  sujets creux laissés passer           : {fn:>3}")
    print(f"\n  justesse globale : {100 * (vp + vn) / juges:.0f} %")
    if vp + fp:
        print(f"  quand il dit CREUX, il a raison dans {100 * vp / (vp + fp):.0f} % des cas")

    print("\n  LECTURE — le chiffre qui décide est celui des bons articles tués.")
    print("  Un juge qui écarte 80 % du creux en sacrifiant 5 % des bons articles")
    print("  est rentable ; le même juge à 30 % de bons articles sacrifiés ne l'est")
    print("  pas, quelle que soit sa justesse globale. Ce compromis se règle en")
    print("  changeant la consigne, pas en changeant de modèle.")

    if erreurs_couteuses:
        print("\n  Bons articles que le juge aurait tués (à relire un par un) :")
        for t in erreurs_couteuses[:10]:
            print(f"    · {t[:72]}")
    if erreurs_manquees:
        print("\n  Sujets creux que le juge a laissés passer :")
        for t in erreurs_manquees[:6]:
            print(f"    · {t[:72]}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
