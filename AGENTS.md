# Consignes pour tout agent travaillant sur ce dépôt

Plusieurs agents (Claude Code, Codex) travaillent sur `lesfaits` en parallèle,
sans canal de communication entre eux. **Le dépôt est le seul point de
rendez-vous.** Ce fichier existe pour qu'on ne se marche pas dessus.

## 1. Lire CLAUDE.md avant d'écrire une ligne

`CLAUDE.md` est la mémoire du projet, pas de la documentation d'ambiance. Il
contient les mesures faites, les décisions prises, **et surtout les pistes
déjà essayées qui ont échoué**. Plusieurs sections y sont écrites précisément
pour empêcher qu'on refasse une erreur :

- le filtre anti-doublon par mots de titre a été rustiné trois fois (26/07,
  28/07, 02/08), chaque fois à l'intuition, chaque fois faux ;
- le juge de sujet (« ce sujet mérite-t-il un article ? ») a rendu 50 % sur un
  jeu équilibré, soit le hasard — ne pas le retenter tel quel ;
- l'hypothèse « les motifs bloquants du 31/07 expliquent le zéro du 01/08 » a
  été réfutée par les données.

Une piste marquée comme écartée dans `CLAUDE.md` l'a été **après mesure**. La
rouvrir demande une nouvelle mesure, pas une nouvelle intuition.

## 2. Mesurer avant de décider — c'est la règle du projet

Ne jamais fixer un seuil sans avoir relevé la distribution qu'il découpe. Ne
jamais ajouter un motif bloquant sans avoir mesuré son taux de déclenchement
sur les articles déjà publiés : au-delà de ~10 % du corpus, il est trop large.

Quand la mesure préalable est impossible, l'ajouter en AVERTISSEMENT d'abord,
et l'écrire.

## 3. Ne jamais assouplir un garde-fou pour publier plus

Le pipeline n'existe pas pour maximiser le nombre d'articles : il existe pour
empêcher qu'un mauvais article soit publié. Un run qui ne publie rien parce que
rien n'a passé les contrôles est un run réussi.

## 4. Le quota Groq est la ressource rare

Les limites sont **par compte, pas par clé** — plusieurs clés d'un même compte
se partagent les mêmes 100 k tokens/jour. Et elles sont **par modèle** : un
petit modèle puise dans un stock que le rédacteur n'utilise pas.

Tout ce qui peut être fait sans jeton doit l'être sans jeton. Une bonne part
des correctifs récents étaient du code pur, mesurables hors ligne sur les 161
articles publiés.

## 5. Éviter les collisions entre agents

- **Un commit = un sujet**, avec un message qui dit ce qui a été MESURÉ et
  pourquoi la décision a été prise. Les messages de ce dépôt sont longs
  volontairement : ils sont lus par l'agent suivant, qui n'a pas votre contexte.
- **Pousser souvent et petit.** Deux agents sur la même branche pendant une
  heure produisent un conflit garanti.
- **Rebaser, jamais forcer.** `git pull --rebase` avant chaque push.
- Avant de modifier un fichier très fréquenté (`scripts/pipeline.py`,
  `scripts/verification.py`), faire un `git fetch` : quelqu'un d'autre y est
  peut-être.

## 6. Fichiers écrits par des automates — ne pas les modifier à la main

`data/veille.json` (passage horaire), `data/articles.json`, `data/*.json` de
diagnostic, `articles/*.html`, `index.html`, `archive.html`, `feed.xml`,
`sitemap.xml` sont générés. En cas de conflit dessus, prendre la version de
`main` et relancer `python scripts/pipeline.py --rebuild`.

## 7. Vérifier avant de pousser

```
python -m pyflakes scripts/*.py | grep -i "undefined name"   # doit être vide
python scripts/check_seo.py                                   # bloquant au déploiement
for t in scripts/test_*.py; do python "$t"; done              # ~31 fichiers
```

`test_pipeline_reel.py` et `test_juge_*.py` appellent les vraies API : ils ne
passent pas hors runner, c'est normal.

⚠ **Un test unitaire ne voit pas un site d'appel.** Le 13/08, un `NameError`
introduit dans un appel a tué deux runs et coûté deux jours de publication,
alors que la fonction appelée était couverte par quatre tests. C'est `pyflakes`
qui attrape cette classe d'erreur, et il est désormais bloquant dans
`pipeline.yml`.

## 8. Ce qui est en cours, et ce qu'il ne faut pas doubler

À la mi-août : la veille continue alimente la sélection (persistance des sujets
dans les fils, dédoublonnage par événement), un juge de pertinence des sources
tourne sur un petit modèle, et le chantier suivant est la QUALITÉ DE RÉDACTION
— deux tiers des articles publiés se répètent, et les détecteurs le voient sans
rien bloquer.

Une décision éditoriale reste ouverte et n'appartient à aucun agent : le
journal s'autorise-t-il à écrire qu'une affirmation publique n'est pas étayée
quand un organisme de vérification le dit ? Ne pas la trancher seul.
