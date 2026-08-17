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

# Fenêtre RACCOURCIE pour les items qu'aucun autre flux n'a repris.
#
# Mesuré au premier passage : 80 % des items restent à un seul flux. Les
# conserver 72 h fait grossir un fichier commité 24 fois par jour — projection
# à fenêtre pleine : plusieurs mégaoctets, soit des centaines de mégaoctets
# d'historique git par mois, pour du bruit que personne ne relira jamais.
#
# Un item qu'aucun autre flux n'a repris en 24 h ne sera pas repris après :
# il ne peut plus franchir aucun seuil de confirmation. On le purge donc plus
# tôt. Tout ce qui a été repris par au moins deux flux — c'est-à-dire tout ce
# qui peut compter — garde la fenêtre complète, et reste donc rejouable si on
# change d'algorithme de regroupement plus tard.
#
# ⚠ « Repris par deux flux » se juge au niveau de la GRAPPE, jamais de l'item.
# Le champ `flux` d'un item ne liste que les flux publiant CETTE URL exacte,
# ce qui est rare : quand neuf rédactions couvrent un séisme, ce sont neuf URLs
# différentes, chacune vue par un seul flux. Un critère par item purgerait donc
# 96 % du journal — mesuré — y compris l'intégralité du séisme. C'est le
# regroupement qui porte le signal, et c'est lui qu'il faut interroger ici.
FENETRE_HEURES_ISOLE = 24

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
    # Écriture compacte : le fichier est réécrit et commité toutes les heures,
    # l'indentation coûte 12 % de volume à chaque fois pour un fichier que
    # personne ne lit à la main (`--rapport` est là pour ça).
    tmp.write_text(json.dumps(journal, ensure_ascii=False, separators=(",", ":")),
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
    limite_isole = maintenant - timedelta(hours=FENETRE_HEURES_ISOLE)
    avant = len(items)

    # Flux distincts de la GRAPPE à laquelle appartient chaque item — voir
    # l'avertissement sur FENETRE_HEURES_ISOLE.
    flux_grappe: dict[str, int] = {}
    for membres in _grouper_membres(items).values():
        n = len({f for k in membres for f in items[k].get("flux", [])})
        for k in membres:
            flux_grappe[k] = n

    def a_garder(cle: str, v: dict) -> bool:
        vue = _parse(v.get("derniere_vue"))
        if not vue:
            # Enregistrement sans date exploitable : on le laisse sortir plutôt
            # que de le garder indéfiniment faute de pouvoir le dater.
            return False
        seuil = limite if flux_grappe.get(cle, 1) >= 2 else limite_isole
        return vue >= seuil

    journal["items"] = {k: v for k, v in items.items() if a_garder(k, v)}
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


def _grouper_membres(items: dict, cles: dict | None = None) -> dict[str, list[str]]:
    """Grappes d'items, sous la forme {clé du chef de file: [clés des membres]}.

    Partagé par `regrouper` (analyse) et par la purge de `collecter` : les deux
    doivent voir exactement les mêmes grappes, sinon la purge jetterait des
    items que le rapport compte encore.

    ⚠ PAS d'union-find, et c'est le résultat d'une mesure, pas un choix de
    style. Le premier passage réel (12/08, 902 items) a été regroupé par
    composantes connexes : A rejoint B, B rejoint C, et de proche en proche
    59 articles sans rapport se retrouvaient dans un même « événement » crédité
    de 20 flux distincts. Les 7 grappes de tête étaient toutes des blobs, donc
    les chiffres les plus intéressants du rapport — ceux du haut du classement
    — étaient précisément les plus faux.

    Regroupement par CHEF DE FILE : un item ne rejoint une grappe que s'il
    partage 2 mots distinctifs avec le PREMIER item de cette grappe, jamais
    avec un membre quelconque. La transitivité est ainsi coupée : la grappe ne
    peut pas dériver loin de ce qu'elle décrivait au départ.
    """
    if cles is None:
        bruyants = _mots_bruyants(items)
        cles = {k: (mots_cles(v.get("titre", "")) - bruyants) for k, v in items.items()}
    grappes: dict[str, list[str]] = {}
    for k in items:
        rejoint = None
        for chef in grappes:
            if len(cles[k] & cles[chef]) >= 2:
                rejoint = chef
                break
        if rejoint is None:
            grappes[k] = [k]
        else:
            grappes[rejoint].append(k)
    return grappes


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

    grappes = _grouper_membres(items, cles)

    maintenant = datetime.now(timezone.utc)
    out = []
    for membres in grappes.values():
        flux, premiere, derniere = set(), None, None
        apparitions = []
        for k in membres:
            v = items[k]
            flux.update(v.get("flux", []))
            p, d = _parse(v.get("premiere_vue")), _parse(v.get("derniere_vue"))
            if p:
                apparitions.append(p)
            premiere = p if premiere is None or (p and p < premiere) else premiere
            derniere = d if derniere is None or (d and d > derniere) else derniere
        heures = (derniere - premiere).total_seconds() / 3600 if premiere and derniere else 0

        # DÉLAI DE CONFIRMATION — la mesure qui décide si attendre coûte cher.
        #
        # Objection de Nahil (12/08) : « lundi tous les journaux parlent du
        # séisme, nous on en parle samedi ». Attendre qu'un sujet soit confirmé
        # par plusieurs reprises n'a de sens que si cette confirmation arrive en
        # HEURES, pas en jours. Personne ne connaît ce délai — on le mesure
        # plutôt que d'en débattre.
        #
        # Défini comme l'écart entre la 1re et la 3e apparition de la grappe :
        # c'est le temps qu'il aurait fallu attendre pour publier sur un critère
        # « au moins 3 reprises ». Vaut None sous 3 items — rien à mesurer.
        delai = None
        if len(apparitions) >= 3:
            tri = sorted(apparitions)
            delai = round((tri[2] - tri[0]).total_seconds() / 3600, 1)

        # ÂGE — l'autre moitié du problème. Un sujet peut être largement
        # confirmé ET trop vieux pour être publié. Les deux critères sont
        # indépendants et devront être exigés ENSEMBLE le jour où la sélection
        # sera branchée dessus.
        age = round((maintenant - premiere).total_seconds() / 3600, 1) if premiere else 0

        out.append({
            "titre": items[membres[0]].get("titre", ""),
            "n_items": len(membres),
            "n_flux": len(flux),
            "heures": round(heures, 1),
            "delai_confirmation": delai,
            "age_h": age,
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

    # Le coût réel d'attendre. Si ce délai se compte en heures, exiger une
    # confirmation ne nous met pas en retard ; s'il se compte en jours, l'idée
    # doit être abandonnée ou le seuil abaissé. C'est la mesure qui tranche.
    delais = [c["delai_confirmation"] for c in grappes
              if c["delai_confirmation"] is not None]
    if delais:
        _histo(delais, (0, 1, 3, 6, 12, 24),
               "DÉLAI DE CONFIRMATION : heures entre la 1re et la 3e reprise")
        print(f"    médiane : {sorted(delais)[len(delais) // 2]:.1f} h "
              f"sur {len(delais)} événements")
    else:
        print("\n  DÉLAI DE CONFIRMATION : pas encore mesurable "
              "(il faut plusieurs passages espacés).")

    interessants = [c for c in grappes if c["n_flux"] >= 3]
    print(f"\n  Événements repris par >=3 flux : {len(interessants)} / {len(grappes)}")

    # Confirmé ET frais : les deux critères doivent tenir ENSEMBLE. Un séisme
    # largement repris mais vieux de trois jours est un sujet manqué, pas un
    # sujet à écrire.
    for age_max in (12, 24, 48):
        n = sum(1 for c in interessants if c["age_h"] <= age_max)
        print(f"    dont apparus il y a moins de {age_max:>2} h : {n}")

    print("\n  Tête de classement (repris par le plus de flux) :")
    for c in grappes[:15]:
        conf = f"{c['delai_confirmation']:>4.1f}h" if c["delai_confirmation"] is not None else "   —"
        print(f"    {c['n_flux']:>2} flux · confirmé en {conf} · âge {c['age_h']:>5.1f} h · "
              f"{c['categorie']:<12} {c['titre'][:52]}")

    par_cat = Counter(c["categorie"] for c in interessants)
    if par_cat:
        print("\n  Répartition par rubrique des événements à >=3 flux :")
        for cat, n in par_cat.most_common():
            print(f"    {cat:<14} {n}")

    print("\n  À relire après quelques jours : la distribution du nombre de flux")
    print("  est-elle assez étalée pour y poser un seuil, ou tout est-il à 1 ?")
    print("  C'est cette réponse qui décide si l'idée tient, pas une intuition.\n")


def signal_editorial(urls: list[str]) -> dict[str, dict]:
    """Signal d'importance du journal de veille, pour une liste d'URLs.

    ── PHASE 2, 14/08 : la veille cesse d'être purement passive ──────────────

    Ce qui est rendu est EXACT, pas heuristique. L'appariement se fait par URL
    canonique — les candidats du pipeline viennent des mêmes flux que la
    veille, donc leur URL est littéralement une clé du journal. Aucun
    rapprochement approximatif n'intervient ici.

    Les deux mesures rendues sont per-item et ne dépendent d'AUCUN
    regroupement :

      passages       — nombre de passages horaires où l'article était encore
                       dans son flux ;
      heures_visible — durée entre la première et la dernière vue.

    C'est un choix de conception, pas un repli. Le nombre de rédactions qui
    couvrent un fait serait un signal plus riche, mais il exige de regrouper
    les articles, et le backtest du 13/08 a montré que notre regroupement
    fusionne des sujets sans rapport. Or un regroupement erroné GONFLE ce
    compteur : un seuil haut y est donc PLUS exposé qu'un seuil bas, pas
    moins. Bâtir la sélection dessus reviendrait à faire confiance à la mesure
    la plus fragile au moment précis où elle décide.

    La persistance dit la même chose autrement : un fait qui compte reste dans
    les fils plusieurs heures, un communiqué disparaît au passage suivant. Elle
    se lit sur un item isolé, sans jamais rien rapprocher.

    `n_flux_grappe` est rendu pour être JOURNALISÉ, jamais pour décider :
    quelques runs diront lequel des deux signaux prédit réellement la
    publication, et c'est cette mesure qui tranchera.

    Ne lève jamais : journal absent, illisible ou vide → dictionnaire vide, et
    l'appelant retombe sur son barème d'origine.
    """
    try:
        journal = charger()
        items = journal.get("items", {})
        if not items:
            return {}
        grappes = _grouper_membres(items)
        flux_par_cle, chef_par_cle = {}, {}
        for chef, membres in grappes.items():
            n = len({f for k in membres for f in items[k].get("flux", [])})
            for k in membres:
                flux_par_cle[k] = n
                chef_par_cle[k] = chef
        maintenant = datetime.now(timezone.utc)
        out: dict[str, dict] = {}
        for url in urls:
            cle = url_canonique(url)
            v = items.get(cle)
            if not v:
                continue
            p, d = _parse(v.get("premiere_vue")), _parse(v.get("derniere_vue"))
            out[url] = {
                # Identifiant de la grappe : sert au pipeline à ne pas retenir
                # DEUX sujets du même événement dans un même run (14/08 — six
                # dépêches sur la censure de l'interdiction des réseaux sociaux
                # occupaient six des onze premières places).
                "grappe": chef_par_cle.get(cle, cle),
                "passages": int(v.get("passages", 1)),
                "heures_visible": round((d - p).total_seconds() / 3600, 1) if p and d else 0.0,
                "age_h": round((maintenant - p).total_seconds() / 3600, 1) if p else 0.0,
                "n_flux_grappe": flux_par_cle.get(cle, 1),
            }
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[VEILLE] signal indisponible ({type(e).__name__}) — barème d'origine")
        return {}


def sources_evenement(url: str, plafond: int = 8) -> list[dict]:
    """Les AUTRES reprises du même événement, telles que la veille les a vues.

    ── L'ÉVÉNEMENT COMME UNITÉ, 17/08 ────────────────────────────────────────

    Jusqu'ici le pipeline notait des dépêches une par une : quand neuf
    rédactions couvraient le même fait, il en retenait une et jetait les huit
    autres comme des doublons. Or ces huit-là sont deux choses à la fois — le
    signal d'importance (déjà exploité par `signal_editorial`) ET la matière :
    huit angles, huit jeux de citations, huit détails que la dépêche retenue
    n'a pas.

    On les rend donc comme sources CANDIDATES. Trois bornes, délibérées :

    - **candidates, pas retenues.** Elles rejoignent le vivier de
      `duckduckgo_search` et passent ensuite par les MÊMES filtres que tout le
      reste — domaines non citables, qualité de source, juge de pertinence,
      `BUDGET_MATIERE`. Aucun chemin privilégié ;
    - **elles ne remplacent aucune recherche.** Ce sont des reprises de presse,
      donc secondaires au mieux : elles ne comblent pas le déficit de sources
      PRIMAIRES, qui reste l'affaire des axes documentaires du 05/08. Ne pas
      attendre d'elles ce qu'elles ne peuvent pas donner ;
    - **plafonnées**, parce qu'une grappe erronée peut compter 30 items (le cas
      « éclipse solaire » du 12/08). Au-delà de `plafond`, on n'ajoute rien : le
      regroupement reste provisoire et ne doit pas décider seul du sourcing.

    Ne lève jamais : journal absent, illisible, URL inconnue → liste vide.
    """
    try:
        journal = charger()
        items = journal.get("items", {})
        cle = url_canonique(url)
        if cle not in items:
            return []
        membres = None
        for chef, m in _grouper_membres(items).items():
            if cle in m:
                membres = m
                break
        if not membres or len(membres) < 2:
            return []
        # ⚠ RÉSULTAT NÉGATIF, 17/08 — ne pas retenter le filtrage par titre ici.
        # Les grappes contiennent du hors-sujet : « Au Japon, des pluies
        # diluviennes » dans celle du séisme en Colombie, « Trump exfiltré en
        # secret » dans celle de son offensive sur les vaccins. Réancrer la
        # règle des 2 mots distinctifs sur le CANDIDAT plutôt que sur le chef de
        # grappe a été essayé et NE FILTRE RIEN : « pluies au Japon » partage
        # « morts » et « moins » avec « 132 morts après le séisme ». Ce sont des
        # mots courants que `_mots_bruyants` ne coupe pas au seuil de 10 %.
        #
        # C'est le même échec que les trois rustinages du filtre anti-doublon
        # (26/07, 28/07, 02/08) : le discriminant n'existe pas dans les titres.
        # On s'en remet donc à l'instrument qui a été MESURÉ sur cette question
        # exacte — le juge de pertinence, dont le backtest du 12/08 n'a jamais
        # déclaré pertinente une source étrangère (0 sur 30). Le hors-sujet
        # arrive donc en queue de tri et n'entre pas dans le prompt.
        out = []
        for k in membres:
            if k == cle or len(out) >= plafond:
                continue
            v = items[k]
            out.append({
                "title": v.get("titre", ""),
                "url": k,
                "snippet": "",
                "institution": (v.get("flux") or [""])[0],
            })
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[VEILLE] reprises indisponibles ({type(e).__name__})")
        return []


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
