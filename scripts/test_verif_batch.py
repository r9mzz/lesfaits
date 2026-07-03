"""Un seul appel detecter() sur le texte final déjà corrigé de
redmi-15-5g-smartphone-abordable (issu du run précédent), pour voir le
détail bloc-par-bloc des problèmes résiduels — en particulier si
compteur_incoherent (désormais bloc 2) se déclenche sur cet article."""
import sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from verification import detecter, ANTHROPIC_KEY

ROOT = Path(__file__).parent.parent


def load_sources(slug):
    path = ROOT / "articles" / f"{slug}.html"
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    sources = []
    for li in soup.select(".sources li"):
        # Deux formats HTML coexistent dans le corpus : <strong> (récent) et
        # <cite> (plus ancien) pour le nom de l'institution.
        inst_el = li.find("strong") or li.find("cite")
        inst = inst_el.get_text(strip=True) if inst_el else ""
        titre_src = li.find("em").get_text(strip=True) if li.find("em") else ""
        a = li.find("a")
        url = a["href"] if a else ""
        sources.append({"institution": inst, "titre": titre_src, "url": url})
    return sources

# Texte final tel qu'obtenu après les 3 tentatives de correction du run précédent
RESUME = ("Le Redmi 15 5G est un smartphone abordable proposé par Xiaomi, équipé d'un écran de 6,9 pouces "
          "avec un taux de rafraîchissement de 144 Hz et d'une batterie de 7000 mAh, selon les tests publiés "
          "par Les Mobiles et Notebookcheck. Ce modèle est actuellement disponible à moins de 150 €, comme "
          "indiqué sur le site de Futura Sciences. Les tests de Les Mobiles et Notebookcheck s'accordent pour "
          "identifier l'endurance comme le principal point fort du modèle, Notebookcheck le qualifiant dans "
          "son titre de « candidat de choix pour le trône de l'autonomie ».")

FAITS = ("D'après les tests de Les Mobiles et Notebookcheck, confirmés par la fiche officielle constructeur "
         "Xiaomi, le Redmi 15 5G est équipé d'un écran de 6,9 pouces avec un taux de rafraîchissement de "
         "144 Hz. Ces deux publications ont mesuré l'autonomie du modèle et concluent, chacune dans son test, "
         "que la batterie de 7000 mAh place l'appareil parmi les smartphones les plus endurants de sa "
         "catégorie : Notebookcheck le présente dans le titre de son test comme « un candidat de choix pour "
         "le trône de l'autonomie ». Le processeur embarqué est un Qualcomm Snapdragon 6s Gen 3, une "
         "caractéristique mentionnée à la fois dans les tests de Les Mobiles et Notebookcheck et dans "
         "l'article de Futura Sciences, qui signale que ce composant équipe ce modèle vendu à moins de 150 €.")

CONTEXTE = ("Selon le test de Les Mobiles, dont le titre indique « endurance et accessibilité au meilleur "
            "niveau » — cadrage éditorial de la publication —, le Redmi 15 5G cible les consommateurs qui "
            "privilégient l'autonomie et le prix d'achat. D'après Futura Sciences, le Redmi 15 5G est "
            "actuellement disponible à moins de 150 €, un positionnement tarifaire qui lui permet de "
            "proposer simultanément un écran 144 Hz, un processeur Snapdragon 6s Gen 3 et une batterie de "
            "7000 mAh. Futura Sciences juge, pour sa part, cette association de caractéristiques comme rare "
            "à ce niveau de prix. Notebookcheck précise par ailleurs, dans son test, que le modèle intègre "
            "la connectivité 5G, ce qui le distingue de plusieurs concurrents directs positionnés dans la "
            "même tranche tarifaire.")

NUANCES = ("Le Redmi 15 5G présente plusieurs limites identifiées par les publications spécialisées. Selon "
           "le test de Notebookcheck, les performances graphiques du modèle sont en retrait, ce qui se "
           "traduit notamment par des résultats limités dans les jeux exigeants. D'après Les Mobiles, la "
           "qualité photographique du Redmi 15 5G reste inférieure à celle de modèles vendus à des tarifs "
           "plus élevés, une limite que la publication documente avec des exemples de clichés comparatifs "
           "dans son test.")

art = {
    "slug": "redmi-15-5g-smartphone-abordable",
    "titre": "Redmi 15 5G : un smartphone abordable",
    "categorie": "tech",
    "resume": RESUME,
    "corps": {"faits": FAITS, "contexte": CONTEXTE, "nuances": NUANCES},
    "sources": load_sources("redmi-15-5g-smartphone-abordable"),
    "nb_sources": 4,  # valeur telle que fixée par le correcteur au run précédent
}

print(f"Clé Anthropic présente : {bool(ANTHROPIC_KEY)}", flush=True)
print(f"Sources autorisées (article original) : {[s['institution'] for s in art['sources']]}", flush=True)

rapport = detecter(art)
print(f"\nconforme : {rapport.get('conforme')}", flush=True)
print(f"sujet_sensible : {rapport.get('sujet_sensible')} ({rapport.get('sujet_sensible_raison','')})", flush=True)
problemes = rapport.get("problemes", [])
print(f"nb problèmes : {len(problemes)}", flush=True)
for i, p in enumerate(problemes, 1):
    print(f"\n  [{i}] bloc={p.get('bloc')} type={p.get('type')} section={p.get('section')}", flush=True)
    print(f"      phrase : {p.get('phrase_exacte','')[:200]}", flush=True)
    print(f"      explication : {p.get('explication','')}", flush=True)
