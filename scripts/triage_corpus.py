"""Tri structurel offline des 108 articles (zéro appel API, ne modifie aucun
article). Calcule par article des signaux déterministes, détecte les doublons,
classe en A (garder) / B (régénérer) / C (purger) par règles explicites, et
écrit un CSV trié pour revue humaine. Heuristiques imparfaites (surtout la
détection de fantômes et de doublons) — donne une cartographie, pas un verdict
définitif article par article."""
import re, csv, unicodedata
from pathlib import Path
from collections import defaultdict
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
ARTICLES = ROOT / "articles"
OUT_CSV = ROOT / "triage_corpus.csv"

MOIS = {m: i for i, m in enumerate(
    ["janvier","février","mars","avril","mai","juin","juillet","août",
     "septembre","octobre","novembre","décembre"], 1)}

GENERIQUES = {
    "les","le","la","l","un","une","des","ce","cette","ces","son","sa","experts",
    "expert","sources","source","etude","etudes","rapport","rapports","ministre",
    "ministere","gouvernement","chercheurs","chercheur","scientifiques","scientifique",
    "autorites","autorite","analystes","analyste","medias","media","donnees",
    "informations","communique","president","directeur","responsable","porte",
    "plusieurs","certains","certaines","nombreux","differentes","premier","premiere",
    "nouvelles","recentes",
}
# Catégories/mots-clés à risque éditorial (sujet sensible probable)
RISQUE_KW = re.compile(
    r"mineur|enfant|mort|décès|deces|tué|tue|viol|meurtre|accident|condamn|"
    r"procès|proces|justice|enquête|enquete|mis en examen|garde à vue|victime|"
    r"pénal|penal|plainte|accus", re.IGNORECASE)


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _mots_sign(titre):
    return {w for w in re.findall(r"[a-zà-ÿ]+", titre.lower()) if len(w) >= 5}


def analyser(path):
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    titre_el = soup.select_one("h1.art__title")
    titre = titre_el.get_text(strip=True) if titre_el else path.stem
    cat_el = soup.select_one("span.art__cat")
    cat = cat_el.get_text(strip=True) if cat_el else ""

    # Date depuis <time> ou le badge
    date_txt = ""
    t = soup.select_one("time")
    if t:
        date_txt = t.get_text(strip=True)
    age_key = 0
    m = re.search(r"(\d{1,2})\s+([a-zà-ÿ]+)\s+(\d{4})", date_txt.lower())
    if m:
        j, mois, an = int(m.group(1)), MOIS.get(m.group(2), 0), int(m.group(3))
        age_key = an * 10000 + mois * 100 + j

    corps = []
    r = soup.select_one("p.art__resume")
    if r:
        corps.append(r.get_text(" ", strip=True))
    for h2 in soup.select("h2.art__h2"):
        p = h2.find_next_sibling("p")
        if p:
            corps.append(p.get_text(" ", strip=True))
    texte = " ".join(corps)
    n_mots = len(texte.split())

    listees = set()
    for li in soup.select(".sources li"):
        el = li.find("strong") or li.find("cite")
        if el:
            listees.add(_norm(el.get_text(strip=True)))

    attributions = re.findall(
        r"(?:Selon|D[''`]apr[eè]s|Pour)\s+([A-Za-zÀ-ÿ0-9][\w'’.\- ]{1,40}?)"
        r"(?=[,.;:]|\s+(?:a|ont|que|qui|le|la|les|dans|sur|pour|est|avait|s['’]))",
        texte)
    nommees = set()
    for att in attributions:
        premier = _norm(att.split()[0]) if att.split() else ""
        if premier and premier not in GENERIQUES:
            nommees.add(_norm(att.strip()))
    fantomes = {n for n in nommees
                if not any(n in l or l in n for l in listees if l)}

    densite = round(len(attributions) / max(n_mots, 1) * 100, 1)
    risque = bool(RISQUE_KW.search(texte))

    return {
        "slug": path.stem, "titre": titre, "cat": cat, "date": date_txt,
        "age_key": age_key, "n_listees": len(listees), "n_fantomes": len(fantomes),
        "n_mots": n_mots, "densite_attr": densite, "risque": risque,
    }


def main():
    fichiers = sorted(ARTICLES.glob("*.html"))
    arts = []
    for f in fichiers:
        try:
            arts.append(analyser(f))
        except Exception as e:
            print(f"[SKIP] {f.name}: {e}")

    # Doublons : titres partageant >=2 mots significatifs (>=5 lettres)
    clusters = defaultdict(list)
    mots = {a["slug"]: _mots_sign(a["titre"]) for a in arts}
    doublon = set()
    for i, a in enumerate(arts):
        for b in arts[i+1:]:
            shared = mots[a["slug"]] & mots[b["slug"]]
            if len(shared) >= 2:
                key = tuple(sorted(shared)[:2])
                clusters[key].append(a["slug"]); clusters[key].append(b["slug"])
                doublon.add(a["slug"]); doublon.add(b["slug"])

    # Classement
    for a in arts:
        a["doublon"] = a["slug"] in doublon
        if a["doublon"] or (a["n_listees"] <= 3 and a["n_fantomes"] >= 2) or a["n_mots"] < 200:
            a["pile"] = "C"
        elif a["n_listees"] >= 5 and a["n_fantomes"] == 0 and not a["risque"] and a["n_mots"] >= 300:
            a["pile"] = "A"
        else:
            a["pile"] = "B"

    from collections import Counter
    piles = Counter(a["pile"] for a in arts)
    print("=" * 90)
    print(f"TRI STRUCTUREL — {len(arts)} articles (offline, heuristique)")
    print("=" * 90)
    for p in ("A", "B", "C"):
        print(f"  Pile {p} : {piles[p]:3d} articles ({100*piles[p]/len(arts):.0f}%)")
    print()
    print("PILE A — candidats à garder (garder/corriger) :")
    aa = [a for a in arts if a["pile"] == "A"]
    if not aa:
        print("  (aucun)")
    for a in sorted(aa, key=lambda x: -x["age_key"]):
        print(f"  {a['n_listees']}src {a['n_fantomes']}fant {a['n_mots']}mots | {a['cat']:14s} | {a['slug']}")
    print()
    print(f"Doublons détectés : {len(doublon)} articles dans {len([c for c in clusters if len(set(clusters[c]))>1])} clusters")
    vus = set()
    for key, membres in clusters.items():
        uniq = sorted(set(membres))
        sig = tuple(uniq)
        if len(uniq) > 1 and sig not in vus:
            vus.add(sig)
            print(f"  [{'+'.join(key)}] {', '.join(uniq)}")

    # CSV complet trié : pile puis santé décroissante
    arts.sort(key=lambda a: (a["pile"], a["n_fantomes"], -a["n_listees"], -a["age_key"]))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pile","slug","titre","categorie","date","sources_listees",
                    "sources_fantomes","mots","densite_attribution","doublon","risque_sensible"])
        for a in arts:
            w.writerow([a["pile"], a["slug"], a["titre"], a["cat"], a["date"],
                        a["n_listees"], a["n_fantomes"], a["n_mots"], a["densite_attr"],
                        "oui" if a["doublon"] else "", "oui" if a["risque"] else ""])
    print(f"\nCSV complet écrit : {OUT_CSV.name} ({len(arts)} lignes)")


if __name__ == "__main__":
    main()
