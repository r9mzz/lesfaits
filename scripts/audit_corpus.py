"""Audit gratuit (zéro appel API) du corpus complet : mesure le pattern
'sources fantômes' — sources citées dans le corps du texte via 'Selon X' /
'D'après X' mais absentes de la liste SOURCES. Heuristique imparfaite
(peut rater des attributions ou en sur-compter), mais donne un ordre de
grandeur réel sur les 99 articles plutôt qu'une extrapolation depuis 9.
Ne modifie aucun fichier."""
import re, unicodedata
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
ARTICLES = ROOT / "articles"

# Attributions génériques (non nominatives) — comptées à part, pas fantômes
GENERIQUES = {
    "les", "le", "la", "l", "un", "une", "des", "ce", "cette", "ces", "son", "sa",
    "experts", "expert", "sources", "source", "etude", "etudes", "rapport", "rapports",
    "ministre", "ministere", "gouvernement", "chercheurs", "chercheur", "scientifiques",
    "scientifique", "autorites", "autorite", "analystes", "analyste", "medias", "media",
    "donnees", "informations", "communique", "president", "directeur", "responsable",
    "porte", "plusieurs", "certains", "certaines", "nombreux", "differentes", "premier",
    "premiere", "nouvelles", "recentes",
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def analyser(path):
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    # Corps = résumé + faits + contexte + nuances
    corps = []
    r = soup.select_one("p.art__resume")
    if r:
        corps.append(r.get_text(" ", strip=True))
    for h2 in soup.select("h2.art__h2"):
        p = h2.find_next_sibling("p")
        if p:
            corps.append(p.get_text(" ", strip=True))
    texte = " ".join(corps)

    # Sources listées (deux formats : <strong> et <cite>)
    listees = set()
    for li in soup.select(".sources li"):
        el = li.find("strong") or li.find("cite")
        if el:
            listees.add(_norm(el.get_text(strip=True)))

    # Attributions dans le texte : "Selon X" / "D'après X" — capture 1 à 3 mots
    attributions = re.findall(
        r"(?:Selon|D[''`]apr[eè]s|Pour)\s+([A-Za-zÀ-ÿ0-9][\w'’.\- ]{1,40}?)(?=[,.;:]|\s+(?:a|ont|que|qui|le|la|les|dans|sur|pour|est|avait|s['’]))",
        texte,
    )

    nommees, vagues = set(), 0
    for att in attributions:
        premier = _norm(att.split()[0]) if att.split() else ""
        if premier in GENERIQUES or not premier:
            vagues += 1
            continue
        nommees.add(_norm(att.strip()))

    # Fantômes : sources nommées dans le texte qui ne matchent aucune source listée
    fantomes = set()
    for n in nommees:
        if not any(n in l or l in n for l in listees if l):
            fantomes.add(n)

    return len(listees), len(nommees), len(fantomes), vagues


def main():
    fichiers = sorted(ARTICLES.glob("*.html"))
    total = len(fichiers)
    avec_fantomes = 0
    somme_listees = somme_fantomes = 0
    pires = []

    for f in fichiers:
        try:
            n_listees, n_nommees, n_fantomes, vagues = analyser(f)
        except Exception as e:
            print(f"[SKIP] {f.name}: {e}")
            continue
        somme_listees += n_listees
        somme_fantomes += n_fantomes
        if n_fantomes > 0:
            avec_fantomes += 1
        pires.append((n_fantomes, n_listees, f.stem))

    pires.sort(reverse=True)
    print("=" * 90)
    print(f"AUDIT CORPUS — {total} articles (heuristique, ordre de grandeur)")
    print("=" * 90)
    print(f"Articles avec >=1 source fantôme (citée mais non listée) : {avec_fantomes}/{total} "
          f"({100*avec_fantomes/total:.0f}%)")
    print(f"Moyenne sources listées / article  : {somme_listees/total:.1f}")
    print(f"Total sources fantômes détectées   : {somme_fantomes}")
    print()
    print("15 pires articles (nb fantômes | nb listées | slug) :")
    for nf, nl, slug in pires[:15]:
        print(f"  {nf:2d} fantôme(s) | {nl} listée(s) | {slug}")
    print()
    # Distribution du nombre de sources listées
    from collections import Counter
    dist = Counter()
    for f in fichiers:
        try:
            n_listees, *_ = analyser(f)
            dist[n_listees] += 1
        except Exception:
            pass
    print("Distribution du nombre de sources listées par article :")
    for n in sorted(dist):
        print(f"  {n} source(s) : {dist[n]} article(s)")


if __name__ == "__main__":
    main()
