# -*- coding: utf-8 -*-
"""VEILLE CONTINUE — phase 1 : observer, mesurer, ne rien décider (12/08).

Idée de Nahil : au lieu de regarder les flux deux fois par jour et de devoir
choisir un sujet sur une PHOTO, les regarder en continu et n'écrire que ce
qui a prouvé son intérêt.

Ce que ça débloque, et qui est impossible sur une photo : la piste écrite dans
CLAUDE.md depuis le 01/08 — « quand 8 flux sur 36 couvrent le même fait, c'est
le signal d'importance le plus fiable disponible ». À 3 h du matin, une dépêche
tombée il y a dix minutes n'a été reprise par personne : elle est indiscernable
d'un sujet mort. C'est le TEMPS qui sépare les deux, et un run ponctuel ne l'a
pas.

┌─────────────────────────────────────────────────────────────────────────────┐
│ CE SCRIPT NE PREND AUCUNE DÉCISION ET N'INFLUENCE PAS `pipeline.py`.        │
│ Il collecte, il compte, il écrit un journal. Rien d'autre. Les seuils       │
│ seront fixés SUR LES DISTRIBUTIONS relevées ici, jamais avant — c'est la    │
│ règle du projet, et c'est précisément celle qu'on a violée trois fois de    │
│ suite sur le filtre anti-doublon (26/07, 28/07, 02/08).                     │
└─────────────────────────────────────────────────────────────────────────────┘

Coût : zéro token Groq. Uniquement des requêtes HTTP vers les flux, déjà
faites par le pipeline — la veille ne touche pas à la ressource rare.

    python scripts/veille.py            # un passage
    python scripts/veille.py --rapport  # relire les distributions sans collecter
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402

JOURNAL = Path(__file__).resolve().parent.parent / "data" / "veille.json"

# Fenêtre d'observation. Un sujet non revu depuis 72 h sort du journal : au-delà
# il n'est plus de l'actualité, et le fichier doit rester lisible et petit
# (il est commité à chaque passage).
FENETRE_HEURES = 72

# Paramètres de tracking à retirer de l'URL avant d'en faire une clé. Sans ça,
# la même dépêche reprise avec un `?xtor=RSS-16` compte comme un item neuf —
# c'est le bug déjà rencontré le 30/07 (« En Gironde, 80 hectares » vu deux
# fois), et il fausserait ici la mesure de persistance.
_PARAMS_TRACKING = re.compile(
    r"^(utm_|xtor|xts|xtc|ref|refid|fbclid|gclid|mc_cid|mc_eid|at_|ns_|cmpid)", re.I)


def url_canonique(url: str) -> str:
    """URL réduite à ce qui identifie le document, tracking retiré."""
    try:
        u = urlparse(url)
    except ValueError:
        return url
    q = [(k, v) for k, v in parse_qsl(u.query) if not _PARAMS_TRACKING.match(k)]
    return urlunparse((u.scheme, u.netloc.lower().removeprefix("www."),
                       u.path.rstrip("/"), "", urlencode(q), ""))


def _sans_accent(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# Mots trop courants pour distinguer deux sujets. Volontairement court : la
# liste longue se règle par la fréquence observée (`_mots_bruyants`), qui
# s'adapte au corpus au lieu d'être devinée.
_VIDES = set("""
les des une un le la de du et en pour sur avec dans par au aux plus son ses
leur leurs ce cette est sont ont fait faire apres avant entre vers chez sans
contre depuis pendant selon dont qui que quoi mais donc car ni or ete etre
premier premiere nouveau nouvelle nouveaux grand grande deux trois ans annee
france francais francaise monde jour jours semaine mois
""".split())


def mots_cles(titre: str) -> set:
    """Mots distinctifs d'un titre, tronqués à 8 caractères.

    La troncature absorbe les variantes singulier/pluriel et les accords
    (« néandertaliens » / « néandertalien »), défaut mesuré le 26/07. La
    ponctuation est retirée AVANT découpage — deux normaliseurs divergents
    dans le même fichier ont déjà produit 61 formes corrompues sur 138 titres
    (constat 02/08, « s'éclipse » → « s'eclips », qui ne matchera jamais
    « eclipse »).
    """
    t = _sans_accent(titre)
    return {m[:8] for m in re.findall(r"[a-z0-9]+", t)
            if len(m) >= 5 and m not in _VIDES}


def charger() -> dict:
    if JOURNAL.exists():
        try:
            return json.loads(JOURNAL.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # Un journal illisible ne doit jamais faire perdre le passage :
            # on repart à vide plutôt que de planter le workflow.
            print(f"[VEILLE] journal illisible ({e}) — repart à vide")
    return {"items": {}, "passages": []}


def enregistrer(journal: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOURNAL.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(journal, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(JOURNAL)


def collecter(journal: dict) -> dict:
    """Un passage : lit tous les flux, met à jour le journal. Aucun jugement."""
    maintenant = datetime.now(timezone.utc)
    horodatage = maintenant.isoformat(timespec="seconds")
    items = journal.setdefault("items", {})
    vus, nouveaux, flux_ok = 0, 0, 0

    for source in P.RSS_SOURCES:
        try:
            lus = P.fetch_rss(source)
        except Exception as e:  # noqa: BLE001 — un flux cassé ne coupe pas la veille
            print(f"[VEILLE] {source['name']} : {type(e).__name__} {e}")
            continue
        if lus:
            flux_ok += 1
        for it in lus:
            cle = url_canonique(it["url"])
            vus += 1
            enr = items.get(cle)
            if enr is None:
                nouveaux += 1
                items[cle] = {
                    "titre": it["title"],
                    "flux": [it["source_name"]],
                    "premiere_vue": horodatage,
                    "derniere_vue": horodatage,
                    "passages": 1,
                    "date_pub": it.get("date", ""),
                    # Catégorie calculée sur le TEASER : ici c'est assumé et
                    # sans conséquence (diagnostic seul). Ne jamais reprendre
                    # cette valeur pour classer un article — le pipeline la
                    # recalcule sur le texte généré depuis le 28/07.
                    "categorie_teaser": P.detect_category(it.get("content", "")),
                }
            else:
                enr["derniere_vue"] = horodatage
                enr["passages"] = enr.get("passages", 0) + 1
                if it["source_name"] not in enr["flux"]:
                    enr["flux"].append(it["source_name"])

    limite = maintenant - timedelta(hours=FENETRE_HEURES)
    avant = len(items)
    journal["items"] = {
        k: v for k, v in items.items()
        if _parse(v.get("derniere_vue")) and _parse(v["derniere_vue"]) >= limite
    }
    purges = avant - len(journal["items"])

    journal.setdefault("passages", []).append({
        "date": horodatage, "flux_utiles": flux_ok,
        "items_vus": vus, "items_neufs": nouveaux, "items_purges": purges,
    })
    journal["passages"] = journal["passages"][-200:]

    print(f"[VEILLE] {horodatage} — {flux_ok}/{len(P.RSS_SOURCES)} flux utiles, "
          f"{vus} items lus, {nouveaux} neufs, {purges} sortis de la fenêtre, "
          f"{len(journal['items'])} suivis")
    return journal


def _parse(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _mots_bruyants(items: dict, plafond: float = 0.10) -> set:
    """Mots présents dans plus de `plafond` des titres de la fenêtre.

    Mesuré en continu plutôt que listé en dur : le vocabulaire de rubrique
    (« canicule » en août, « budget » en octobre) change avec l'actualité, et
    une liste figée devient fausse un mois plus tard.
    """
    if not items:
        return set()
    df = Counter()
    for v in items.values():
        df.update(mots_cles(v.get("titre", "")))
    seuil = max(2, int(len(items) * plafond))
    return {m for m, n in df.items() if n > seuil}


def regrouper(items: dict) -> list[dict]:
    """Regroupe les items en événements présumés.

    ⚠ MÉTHODE PROVISOIRE, ET C'EST VOLONTAIRE. Le recoupement par mots de
    titre a échoué trois fois (26/07, 28/07, 02/08) et CLAUDE.md interdit d'en
    tenter un quatrième comme solution. Ici il ne sert qu'à AFFICHER des
    distributions : le journal conserve chaque item séparément, donc on peut
    rejouer un autre regroupement sur les mêmes données sans rien recollecter.
    C'est tout l'intérêt de séparer la collecte de l'analyse.
    """
    bruyants = _mots_bruyants(items)
    cles = {k: (mots_cles(v.get("titre", "")) - bruyants) for k, v in items.items()}
    parent: dict = {}

    def racine(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    liste = list(items)
    index = defaultdict(list)
    for k in liste:
        for m in cles[k]:
            index[m].append(k)
    for _, groupe in index.items():
        for autre in groupe[1:]:
            a, b = racine(groupe[0]), racine(autre)
            # Deux mots distinctifs partagés, jamais un seul : sur les titres
            # publiés, un seul mot commun rejetait 49 % des paires (28/07).
            if a != b and len(cles[groupe[0]] & cles[autre]) >= 2:
                parent[b] = a

    grappes = defaultdict(list)
    for k in liste:
        grappes[racine(k)].append(k)

    out = []
    for membres in grappes.values():
        flux, premiere, derniere = set(), None, None
        for k in membres:
            v = items[k]
            flux.update(v.get("flux", []))
            p, d = _parse(v.get("premiere_vue")), _parse(v.get("derniere_vue"))
            premiere = p if premiere is None or (p and p < premiere) else premiere
            derniere = d if derniere is None or (d and d > derniere) else derniere
        heures = (derniere - premiere).total_seconds() / 3600 if premiere and derniere else 0
        out.append({
            "titre": items[membres[0]].get("titre", ""),
            "n_items": len(membres),
            "n_flux": len(flux),
            "heures": round(heures, 1),
            "categorie": items[membres[0]].get("categorie_teaser", ""),
        })
    return sorted(out, key=lambda c: (-c["n_flux"], -c["n_items"]))


def _histo(valeurs, seuils, libelle):
    print(f"\n  {libelle}")
    total = max(len(valeurs), 1)
    for bas, haut in zip(seuils, list(seuils[1:]) + [None]):
        n = sum(1 for v in valeurs if v >= bas and (haut is None or v < haut))
        etiquette = f">={bas}" if haut is None else f"{bas}–{haut - 1}"
        print(f"    {etiquette:>8} : {n:>4}  ({100 * n / total:>4.1f} %)"
              + "  " + "█" * min(40, round(40 * n / total)))


def rapport(journal: dict) -> None:
    items = journal.get("items", {})
    if not items:
        print("[VEILLE] journal vide — lancer au moins un passage.")
        return
    grappes = regrouper(items)
    passages = journal.get("passages", [])
    couverture = 0.0
    if len(passages) >= 2:
        d0, d1 = _parse(passages[0]["date"]), _parse(passages[-1]["date"])
        couverture = (d1 - d0).total_seconds() / 3600 if d0 and d1 else 0

    print("\n" + "=" * 74)
    print(f"VEILLE — {len(items)} items suivis, {len(grappes)} événements présumés, "
          f"{len(passages)} passages sur {couverture:.0f} h")
    print("=" * 74)
    print("  DIAGNOSTIC SEUL — aucun seuil n'est fixé ici, aucune décision n'est prise.")

    _histo([c["n_flux"] for c in grappes], (1, 2, 3, 5, 8),
           "Nombre de FLUX DISTINCTS par événement (signal d'importance)")
    _histo([c["heures"] for c in grappes], (0, 1, 6, 24),
           "PERSISTANCE : heures entre première et dernière apparition")

    interessants = [c for c in grappes if c["n_flux"] >= 3]
    print(f"\n  Événements repris par >=3 flux : {len(interessants)} / {len(grappes)}")
    print("\n  Tête de classement (repris par le plus de flux) :")
    for c in grappes[:15]:
        print(f"    {c['n_flux']:>2} flux · {c['heures']:>5.1f} h · "
              f"{c['categorie']:<12} {c['titre'][:64]}")

    par_cat = Counter(c["categorie"] for c in interessants)
    if par_cat:
        print("\n  Répartition par rubrique des événements à >=3 flux :")
        for cat, n in par_cat.most_common():
            print(f"    {cat:<14} {n}")

    print("\n  À relire après quelques jours : la distribution du nombre de flux")
    print("  est-elle assez étalée pour y poser un seuil, ou tout est-il à 1 ?")
    print("  C'est cette réponse qui décide si l'idée tient, pas une intuition.\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rapport", action="store_true",
                    help="afficher les distributions sans collecter")
    args = ap.parse_args()

    journal = charger()
    if not args.rapport:
        journal = collecter(journal)
        enregistrer(journal)
    rapport(journal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
