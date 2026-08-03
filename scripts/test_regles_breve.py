# -*- coding: utf-8 -*-
"""Non-régression des règles 6 et 14 de SYSTEM_PROMPT_BREVE (03/08).

Vérifie que la CONSIGNE et les GARDE-FOUS disent la même chose : la forme que
le prompt interdit doit déclencher un détecteur, la forme qu'il prescrit ne
doit en déclencher aucun. Sans ce test, on peut durcir le prompt sans savoir
si le pipeline sait reconnaître le résultat attendu.

Les textes sont ceux réellement publiés les 02 et 03/08, et leur réécriture
selon les règles. Aucun appel réseau, aucun token : lançable à tout moment.

    python scripts/test_regles_breve.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
import pipeline as P  # noqa: E402

SRC = [{"institution": n, "titre": "T", "date": "3 août 2026", "url": u} for n, u in [
    ("Libération", "https://www.liberation.fr/societe/a"),
    ("RTBF", "https://www.rtbf.be/article/b"),
    ("20 Minutes", "https://www.20minutes.fr/societe/c"),
    ("Radiofrance", "https://www.radiofrance.fr/d"),
    ("RTL", "https://www.rtl.fr/actu/e"),
    ("BFM TV", "https://www.bfmtv.com/f"),
    ("France Info", "https://www.francetvinfo.fr/g"),
]]

# ── Cas 1 : empilement « une phrase = une source » (brève Seveso, 03/08) ──────
SEVESO_PUBLIE_RESUME = ["Une situation d’urgence a nécessité la mise en confinement temporaire "
                        "de milliers d’habitants en Moselle."]
SEVESO_PUBLIE_FAITS = (
    "D’après Libération, RTBF et 20 Minutes, un incendie s’est déclaré dans un entrepôt "
    "classé Seveso « seuil bas » en Moselle, conduisant à la mise en confinement de 30 000 habitants. "
    "Selon RTBF, les communes concernées incluent Gandrange, Amnéville, Vitry-sur-Orne, Clouange et Rombas. "
    "D’après Radiofrance, l’incendie a été maîtrisé, ce qui a permis la levée du confinement. "
    "Selon BFM TV, la préfecture de Moselle a appelé les habitants à se confiner en raison de l’incendie. "
    "D’après RTL, l’incendie a été déclaré dans un entrepôt de la société Safe. "
    "France Info rapporte que les habitants ont été pris en charge."
)
SEVESO_REGLES_RESUME = ["Un incendie dans un entrepôt classé Seveso à Gandrange a conduit au confinement "
                        "de 30 000 habitants en Moselle dimanche matin."]
SEVESO_REGLES_FAITS = (
    "Selon Libération, RTBF et Radiofrance, le sinistre a touché un entrepôt de 500 mètres carrés "
    "de la société Safe, dans la zone industrielle de Gandrange. "
    "Les communes concernées sont Gandrange, Amnéville, Vitry-sur-Orne, Clouange et Rombas. "
    "La préfecture de Moselle avait appelé les habitants à rester chez eux. "
    "L’incendie a été maîtrisé en fin de matinée et le confinement levé. "
    "Aucun blessé n’a été signalé à ce stade. "
    "L’entrepôt est classé Seveso « seuil bas », le niveau le plus faible de la directive européenne."
)

# ── Cas 2 : chapeau ≡ attaque de « faits » (brève Baignade, 02/08) ────────────
BAIGNADE_PUBLIE_RESUME = ["La baignade en zone non autorisée est désormais passible d’une amende de 68 euros, "
                          "dans le but de protéger les personnes qui s’exposent à un danger grave. "
                          "Cette mesure vise à prévenir les noyades, qui ont déjà coûté la vie à 197 personnes "
                          "depuis le début de l’été, selon Lepopulaire."]
BAIGNADE_PUBLIE_FAITS = (
    "La baignade en zone non autorisée est désormais passible d’une amende de 68 euros, "
    "contre 38 euros auparavant. "
    "Le montant peut être dressé directement par procès-verbal électronique. "
    "Depuis le début de l’été, 197 personnes ont perdu la vie par noyade. "
    "Les sanctions sont renforcées à compter de ce dimanche 2 août."
)

DETECTEURS = [
    ("sources_non_fusionnees", P.sources_non_fusionnees),
    ("attributions_trop_repetitives", P.attributions_trop_repetitives),
    ("resume_repete_corps", P.resume_repete_corps),
    ("faits_repetitifs", P.faits_repetitifs),
    ("cliches_ia", P.cliches_ia),
    ("prise_de_position", P.prise_de_position),
]


def _art(resume, faits, slug):
    return {"titre": "Incendie dans un entrepôt Seveso en Moselle", "slug": slug,
            "resume": resume, "corps": {"faits": faits, "contexte": "", "nuances": ""},
            "sources": SRC, "categorie": "environnement", "nb_sources": 7,
            "positions": {"verifie": False, "acteurs": []}}


# attendu : True = au moins un détecteur doit voir le défaut
#           False = la forme prescrite ne doit rien déclencher
#           None = ANGLE MORT connu, aucun détecteur ne voit le défaut
CAS = [
    ("Seveso — forme PUBLIÉE (empilement, règle 6)", _art(SEVESO_PUBLIE_RESUME, SEVESO_PUBLIE_FAITS, "a"), True),
    ("Seveso — forme PRESCRITE par la règle 6", _art(SEVESO_REGLES_RESUME, SEVESO_REGLES_FAITS, "b"), False),
    ("Baignade — chapeau ≡ attaque (règle 14)", _art(BAIGNADE_PUBLIE_RESUME, BAIGNADE_PUBLIE_FAITS, "c"), None),
]


def main() -> int:
    echecs = 0
    for label, a, attendu in CAS:
        print("=" * 70)
        print(label)
        vus = []
        for nom, fn in DETECTEURS:
            r = fn(a)
            if r:
                vus.append(nom)
                print(f"  {nom:30} → DÉCLENCHE  {str(r[0])[:80]}")
        if not vus:
            print("  (aucun détecteur ne déclenche)")
        print(f"  mots : {P._mots_totaux(a)} · plancher brève : {P._seuils('breve')['plancher']}")

        if attendu is None:
            # ANGLE MORT MESURÉ le 03/08 : `resume_repete_corps` compare
            # l'élément de `resume` ENTIER à chaque phrase de « faits ». Ici le
            # chapeau fait 283 caractères (deux phrases là où le prompt en
            # demande une) contre 110 pour l'attaque : le ratio difflib tombe à
            # 0,489 alors que le seuil est 0,55. Comparées phrase à phrase, les
            # deux donnent 0,705 et le détecteur verrait le défaut.
            # C'est pour cela que la règle 14 est la SEULE parade disponible
            # aujourd'hui : rien ne détecte ce défaut en aval.
            # Si ce cas se met à déclencher, c'est que le détecteur a été
            # corrigé — mettre alors `attendu` à True.
            print("  ANGLE MORT connu (ratio 0,489 < seuil 0,55) → "
                  f"{'toujours aveugle, conforme' if not vus else 'DÉTECTEUR CORRIGÉ : passer attendu à True'}")
            continue

        ok = bool(vus) == attendu
        print(f"  ATTENDU : {'déclenchement' if attendu else 'aucun déclenchement'} → {'OK' if ok else 'ÉCHEC'}")
        echecs += 0 if ok else 1

    print("=" * 70)
    print("TOUS LES CAS CONFORMES" if not echecs else f"{echecs} CAS EN ÉCHEC")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
