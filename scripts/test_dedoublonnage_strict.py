import sys, os
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path("scripts").resolve()))
os.environ.setdefault("GROQ_API_KEY", "x")
import pipeline as P

e = []
def v(lib, cond, det=""):
    print(("  OK   " if cond else "  ÉCHEC ") + lib + ("" if cond else f" {det}"))
    if not cond: e.append(lib)

print("Dédoublonnage strict (phrases répétées mot pour mot)")
PH = "La gestion sanitaire des vagues de chaleur est un enjeu important pour les autorités."
art = {"resume": "Chapeau.", "corps": {"faits": f"{PH} Un fait neuf et distinct ici même.",
       "contexte": f"Autre chose de long et suffisamment différent pour rester. {PH}",
       "nuances": ""}}
n = P._supprimer_phrases_identiques(art)
v("la répétition littérale est retirée", n == 1, f"(n={n})")
v("la première occurrence est gardée", PH in art["corps"]["faits"])
v("la copie a disparu", PH not in art["corps"]["contexte"])
v("le reste est intact", "Un fait neuf et distinct ici même." in art["corps"]["faits"])

# Ponctuation, casse et accents ignorés — mais RIEN d'autre.
art2 = {"resume": "", "corps": {"faits": f"{PH} {PH.upper().replace('.', ' !')}",
        "contexte": "", "nuances": ""}}
v("casse et ponctuation ignorées", P._supprimer_phrases_identiques(art2) == 1)

# Deux phrases proches mais NON identiques doivent être conservées : c'est
# précisément ce que la variante permissive supprimait à tort.
proches = {"resume": "", "corps": {
    "faits": ("Les conséquences d'un arrêt de l'AMOC seraient considérables en Europe du Nord. "
              "Les conséquences d'un ralentissement de l'AMOC restent débattues par les chercheurs."),
    "contexte": "", "nuances": ""}}
v("deux phrases proches mais distinctes sont conservées",
  P._supprimer_phrases_identiques(proches) == 0)

# Une phrase du corps qui recopie le chapeau saute ; le chapeau ne bouge pas.
c = {"resume": PH, "corps": {"faits": f"{PH} Autre chose entièrement différente ici.",
     "contexte": "", "nuances": ""}}
P._supprimer_phrases_identiques(c)
v("le résumé n'est jamais modifié", c["resume"] == PH)
v("la recopie du chapeau dans le corps saute", PH not in c["corps"]["faits"])

# Article sans doublon : aucune modification.
sain = {"resume": "", "corps": {"faits": "Une phrase parfaitement unique et assez longue ici.",
        "contexte": "", "nuances": ""}}
avant = dict(sain["corps"])
v("un article sain n'est pas touché",
  P._supprimer_phrases_identiques(sain) == 0 and sain["corps"] == avant)

print()
sys.exit(1 if e else 0)
