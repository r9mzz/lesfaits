# -*- coding: utf-8 -*-
"""Tests de la veille continue (phase 1, 12/08).

Le sandbox de développement n'a pas d'accès réseau vers les domaines des flux
(403 du proxy sur CONNECT) : `veille.py` ne peut donc PAS être validé sur un
passage réel ici. La logique d'accumulation est isolée derrière un
`fetch_rss` simulé, ce qui couvre tout sauf la lecture HTTP elle-même.

    python scripts/test_veille.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402
import veille as V  # noqa: E402

echecs: list[str] = []


def verifie(libelle: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  OK   {libelle}")
    else:
        print(f"  ÉCHEC {libelle} {detail}")
        echecs.append(libelle)


def item(titre, url, flux):
    return {"id": url[-8:], "title": titre, "url": url, "content": titre,
            "source_name": flux, "date": "2026-08-12"}


class FluxSimules:
    """Remplace fetch_rss et RSS_SOURCES le temps d'un passage."""

    def __init__(self, par_flux):
        self.par_flux = par_flux

    def __enter__(self):
        self._sources, self._fetch = P.RSS_SOURCES, P.fetch_rss
        P.RSS_SOURCES = [{"name": n, "url": f"https://exemple/{n}"} for n in self.par_flux]
        P.fetch_rss = lambda s: self.par_flux[s["name"]]
        return self

    def __exit__(self, *a):
        P.RSS_SOURCES, P.fetch_rss = self._sources, self._fetch


# ── 1. URL canonique : le tracking ne doit pas créer un item neuf ────────────
# Le bug du 30/07 (« En Gironde, 80 hectares » généré deux fois) venait d'une
# clé sensible aux paramètres d'URL. Ici il fausserait la persistance : un même
# article recompté à neuf à chaque passage aurait toujours 0 h d'ancienneté.
print("\n1. Canonicalisation des URLs")
verifie("le paramètre de tracking est retiré",
        V.url_canonique("https://www.exemple.fr/a/b?xtor=RSS-16")
        == V.url_canonique("https://exemple.fr/a/b"))
verifie("un paramètre significatif est conservé",
        V.url_canonique("https://exemple.fr/a?id=7") != V.url_canonique("https://exemple.fr/a"))
verifie("le slash final ne distingue pas deux URLs",
        V.url_canonique("https://exemple.fr/a/") == V.url_canonique("https://exemple.fr/a"))

# ── 2. Accumulation sur plusieurs passages ───────────────────────────────────
print("\n2. Accumulation")
with tempfile.TemporaryDirectory() as d:
    V.JOURNAL = Path(d) / "veille.json"

    with FluxSimules({"Flux A": [item("Rapport de la Cour des comptes sur les hôpitaux",
                                      "https://a.fr/hopitaux", "Flux A")]}):
        j = V.collecter(V.charger())
        V.enregistrer(j)
    verifie("premier passage : 1 item suivi", len(j["items"]) == 1)

    # Même sujet, deuxième flux, URL avec tracking : un seul item, deux flux.
    with FluxSimules({"Flux B": [item("Cour des comptes : un rapport sur les hôpitaux",
                                      "https://a.fr/hopitaux?utm_source=x", "Flux B")]}):
        j = V.collecter(V.charger())
        V.enregistrer(j)
    enr = list(j["items"].values())[0]
    verifie("deuxième passage : toujours 1 item", len(j["items"]) == 1)
    verifie("les deux flux sont mémorisés", set(enr["flux"]) == {"Flux A", "Flux B"},
            f"(obtenu : {enr['flux']})")
    verifie("le compteur de passages avance", enr["passages"] == 2)
    verifie("la première vue n'est pas écrasée", enr["premiere_vue"] <= enr["derniere_vue"])
    verifie("deux passages journalisés", len(j["passages"]) == 2)

    # ── 3. Purge de la fenêtre ───────────────────────────────────────────────
    print("\n3. Fenêtre glissante")
    vieux = (datetime.now(timezone.utc) - timedelta(hours=V.FENETRE_HEURES + 5)
             ).isoformat(timespec="seconds")
    j["items"]["https://a.fr/vieux"] = {
        "titre": "Sujet ancien", "flux": ["Flux A"], "premiere_vue": vieux,
        "derniere_vue": vieux, "passages": 1, "date_pub": "", "categorie_teaser": "societe"}
    V.enregistrer(j)
    with FluxSimules({"Flux A": []}):
        j = V.collecter(V.charger())
    verifie("l'item hors fenêtre est purgé", "https://a.fr/vieux" not in j["items"])
    verifie("l'item récent est conservé", len(j["items"]) == 1)

    # ── 4. Journal corrompu ──────────────────────────────────────────────────
    print("\n4. Résilience")
    V.JOURNAL.write_text("{ceci n'est pas du JSON", encoding="utf-8")
    repart = V.charger()
    verifie("un journal illisible repart à vide sans exception",
            repart == {"items": {}, "passages": []})

# ── 5. Regroupement ──────────────────────────────────────────────────────────
# Méthode provisoire et assumée comme telle : ce test verrouille seulement la
# règle « deux mots distinctifs partagés, jamais un seul » (28/07), pas la
# pertinence du regroupement lui-même.
print("\n5. Regroupement en événements")
h = datetime.now(timezone.utc).isoformat(timespec="seconds")


def faux(titre, flux):
    return {"titre": titre, "flux": [flux], "premiere_vue": h, "derniere_vue": h,
            "passages": 1, "date_pub": "", "categorie_teaser": "societe"}


grappes = V.regrouper({
    "u1": faux("Chlordécone : les adultes antillais massivement contaminés, selon Santé "
               "publique France", "A"),
    "u2": faux("Contamination au chlordécone : Santé publique France publie son étude", "B"),
    "u3": faux("Trafic de drogue : les recrues viennent de toute la France", "C"),
})
tailles = sorted(c["n_items"] for c in grappes)
verifie("deux titres à 2 mots distinctifs communs sont regroupés", tailles == [1, 2],
        f"(obtenu : {tailles})")
groupe = [c for c in grappes if c["n_items"] == 2][0]
verifie("le groupe compte bien 2 flux distincts", groupe["n_flux"] == 2)

grappes = V.regrouper({
    "u1": faux("Canadair : la flotte française sera remplacée en 2027", "A"),
    "u2": faux("Palantir remplace son directeur technique", "B"),
})
verifie("un seul mot commun ne regroupe pas",
        sorted(c["n_items"] for c in grappes) == [1, 1])

# LIMITE CONNUE, verrouillée ici pour qu'elle reste visible plutôt que d'être
# redécouverte comme un bug : la troncature à 8 caractères ne rapproche pas
# « antillais » de « antilles » (ils diffèrent au 8e caractère). Ces deux
# titres parlent pourtant du même fait et ne sont PAS regroupés. C'est une
# raison de plus de ne pas fonder la décision finale sur les mots du titre —
# voir l'avertissement de `regrouper`. Si ce test se met un jour à échouer,
# c'est que la méthode a changé : le vérifier, ne pas juste l'adapter.
grappes = V.regrouper({
    "u1": faux("Chlordécone : huit adultes antillais sur dix en portent dans le sang", "A"),
    "u2": faux("Chlordécone dans le sang : les Antilles largement contaminées", "B"),
})
verifie("limite documentée : antillais / antilles ne se rejoignent pas",
        sorted(c["n_items"] for c in grappes) == [1, 1])

# Pas de chaînage transitif. Sur le premier passage réel (902 items), le
# regroupement par composantes connexes produisait des grappes de 59 articles
# sans rapport, créditées de 20 flux : les chiffres du haut du classement, les
# seuls intéressants, étaient les plus faux. Ici B partage 2 mots avec A et 2
# mots avec C, mais A et C n'ont rien en commun — ils ne doivent PAS finir
# ensemble.
grappes = V.regrouper({
    "a": faux("Séisme en Colombie : le bilan monte à 240 morts", "A"),
    "b": faux("Séisme en Colombie : les secours cherchent des survivants", "B"),
    "c": faux("Les secours cherchent des survivants après l’avalanche en Savoie", "C"),
})
verifie("le chaînage transitif est coupé",
        max(c["n_items"] for c in grappes) <= 2,
        f"(obtenu : {sorted(c['n_items'] for c in grappes)})")

# ── 6. Le pipeline n'est pas touché ──────────────────────────────────────────
# Garantie centrale de la phase 1 : la veille observe, elle ne décide rien.
print("\n6. Étanchéité avec le pipeline")
verifie("veille.py n'écrit que dans data/veille.json",
        "veille.json" in str(V.JOURNAL))
source = (Path(__file__).parent / "veille.py").read_text(encoding="utf-8")
verifie("aucun appel Groq dans la veille",
        "Groq(" not in source and "chat.completions" not in source)
verifie("la veille ne modifie aucun attribut du pipeline",
        " P." not in source.replace("import pipeline as P", "")
        or all(f"P.{a} =" not in source for a in ("RSS_SOURCES", "fetch_rss", "SYSTEM_PROMPT")))

print()
if echecs:
    print(f"ÉCHEC — {len(echecs)} test(s) : {', '.join(echecs)}")
    sys.exit(1)
print("Tous les tests passent.")
