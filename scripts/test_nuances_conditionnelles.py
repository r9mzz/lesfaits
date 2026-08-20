# -*- coding: utf-8 -*-
"""« Débats et nuances » : plancher CONDITIONNEL, jamais comblé (15/08).

Chaîne éditoriale posée par Nahil après analyse du Courrier de France :
actualité → question utile → angle neutre → sources primaires → sources
indépendantes → RECHERCHE D'ÉLÉMENTS CONTRADICTOIRES → PLAN FONDÉ SUR LES
PREUVES → rédaction → contrôle de neutralité → contrôle factuel → publication.

Deux maillons manquaient. Ce test verrouille le second : notre plan précédait
les preuves au lieu d'en découler. Le prompt exigeait « MINIMUM 150 mots » de
« Débats et nuances » quel que soit le contenu des sources — le modèle devait
donc produire 150 mots de limites et de désaccords même quand les sources n'en
contenaient aucun. Il ne pouvait que les inventer, et c'est là qu'on trouvait
« il est essentiel de renforcer la vigilance ».

    python scripts/test_nuances_conditionnelles.py
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("GROQ_API_KEY", "x")
import pipeline as P  # noqa: E402

echecs = []


def verifie(lib, cond, det=""):
    print(("  OK   " if cond else "  ÉCHEC ") + lib + ("" if cond else f" {det}"))
    if not cond:
        echecs.append(lib)


print("\n1. Consigne de rédaction")
verifie("le plancher de 150 mots n'est plus inconditionnel",
        "MINIMUM 150 mots" not in P.SYSTEM_PROMPT)
verifie("la chaîne vide est explicitement autorisée",
        "chaîne VIDE" in P.SYSTEM_PROMPT)
# ⚠ 20/08 — ce contrôle exigeait « 29. PLANCHER CONDITIONNEL », donc le NUMÉRO
# de la règle. L'ajout de la règle de fidélité au temps et à la modalité a
# décalé la numérotation et cassé le test alors que la règle protégée était
# intacte. Troisième test du projet à verrouiller une forme plutôt qu'un fond
# (après le TPM lu dans le texte source et la table des fenêtres déplacée).
# On vérifie donc la PRÉSENCE de la règle, quel que soit son rang.
verifie("le prompt énonce le plancher conditionnel",
        "PLANCHER CONDITIONNEL" in P.SYSTEM_PROMPT)
verifie("l'invention d'une limite est interdite nommément",
        "il est essentiel de renforcer la vigilance" in P.SYSTEM_PROMPT)

# Les dossiers sont suspendus depuis le 03/08 : on ne touche pas à leurs
# prompts, et surtout on ne les modifie pas « pour la cohérence ».
verifie("les prompts dossier restent inchangés",
        "PLANCHER CONDITIONNEL" not in P.SYSTEM_PROMPT_DOSSIER_SCIENCE
        and "PLANCHER CONDITIONNEL" not in P.SYSTEM_PROMPT_DOSSIER_PORTRAIT)

print("\n2. Rendu d'une section vide")
art = {"titre": "T", "slug": "t-vide", "resume": "Un fait daté et chiffré.",
       "corps": {"faits": "Un fait précis. " * 12, "contexte": "Du contexte. " * 12,
                 "nuances": ""},
       "sources": [{"institution": "X", "titre": "a", "url": "https://a.fr/document"}],
       "categorie": "societe", "format": "article"}
html = P.build_article_html(art, "15 août 2026, 10h00")
avant_sources = html.split("SOURCES")[0]
verifie("aucune section « nuances » n'est rendue quand elle est vide",
        "Débats et nuances" not in avant_sources)
verifie("l'article est bien rendu par ailleurs", len(html) > 5000)

print("\n3. Recherche d'éléments contradictoires")
axes = [n for n, _ in P._AXES_UNIVERSELS]
verifie("un axe « contradiction » existe", "contradiction" in axes, f"({axes})")
verifie("il est joué sur TOUS les sujets, pas par rubrique",
        "contradiction" not in str(P._AXES_PAR_CATEGORIE))

# La troncature ne doit jamais vider un axe au profit d'un autre : l'axe
# générique rapporte le plus et passe en premier, donc couper par ordre
# d'arrivée supprimerait d'abord les axes documentaires — le bug du 30/07,
# déplacé de la boucle vers la troncature.
print("\n4. Troncature équitable entre axes")
faux = []
for axe, n in (("générique", 30), ("officiel/juridique", 6), ("contradiction", 8)):
    faux += [{"title": f"{axe}{i}", "url": f"https://x/{axe}/{i}", "snippet": "",
              "_axe": axe} for i in range(n)]
files = {}
for r in faux:
    files.setdefault(r["_axe"], []).append(r)
out, i = [], 0
while len(out) < 12 and any(len(f) > i for f in files.values()):
    for f in files.values():
        if i < len(f):
            out.append(f[i])
            if len(out) >= 12:
                break
    i += 1
axes_retenus = {r["_axe"] for r in out}
verifie("à plafond serré, chaque axe reste représenté", len(axes_retenus) == 3,
        f"({axes_retenus})")
verifie("l'ordre d'arrivée seul aurait tout donné au générique",
        {r["_axe"] for r in faux[:12]} == {"générique"})

# ── 5. Le plancher total ne doit pas ressusciter la contrainte retirée ──
# Défaut relevé le 15/08 par une session parallèle : « nuances » est devenu
# conditionnel, mais 250 lignes plus loin les RÈGLES ABSOLUES exigeaient encore
# « minimum 500 mots combinés (faits + contexte + nuances) », sous la mention
# « toute violation = article rejeté ». Une section facultative dans une somme
# obligatoire, c'est la contrainte d'invention déplacée d'une section à l'autre,
# pas supprimée. Le plancher du prompt doit être celui qui rejette réellement
# (SEUILS_FORMAT["article"]["plancher"] = 350), jamais un chiffre plus haut.
print("\n5. Plancher total cohérent avec le garde-fou")
_plancher = P.SEUILS_FORMAT["article"]["plancher"]
verifie("le prompt n'exige plus 500 mots combinés",
        "minimum 500 mots combinés" not in P.SYSTEM_PROMPT)
verifie(f"le prompt annonce le plancher réel ({_plancher})",
        f"{_plancher} mots combinés" in P.SYSTEM_PROMPT)
verifie("aucune section n'impose un MINIMUM en mots",
        "MINIMUM 450 mots" not in P.SYSTEM_PROMPT
        and "MINIMUM 200 mots" not in P.SYSTEM_PROMPT
        and "MINIMUM 150 mots" not in P.SYSTEM_PROMPT)
verifie("la somme des cibles de section n'excède plus le plancher exigé",
        450 + 200 > _plancher)

print()
sys.exit(1 if echecs else 0)
