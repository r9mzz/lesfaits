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

## 8. Ajouter des sources — le piège qui annule tout le travail

**Un nouveau domaine doit être inscrit dans `_DOMAINES_PRIMAIRES` ou
`_DOMAINES_SECONDAIRES` (`scripts/pipeline.py`), sinon il ne vaut rien.**

La règle de publication est « au moins 1 source primaire OU 2 secondaires
indépendantes ». Un domaine absent de ces listes compte **tertiaire**, quel que
soit son sérieux : la Cour des comptes non déclarée pèse autant que Wikipédia.
Le pipeline ira chercher l'excellente source, la citera… et le contrôle
l'ignorera. Panne silencieuse, aucun message d'erreur.

⚠ Ces listes sont **distinctes de `_SOURCE_DOMAINS`** (choix d'image et droits
voisins, 4 entrées). Modifier l'une ne modifie pas l'autre. État actuel :
60 domaines primaires, 45 secondaires, 38 flux RSS.

**Ne jamais ajouter un flux sans mesurer son rendement réel.** La vague
d'ajouts du 19/07 comptait 13 flux morts sur 14, ajoutés sans test — mesuré le
28/07. Le sandbox de développement n'a PAS d'accès réseau vers ces domaines :
une URL ne peut donc pas y être validée. Utiliser `scripts/check_feeds.py` via
`.github/workflows/check_feeds.yml`, qui mesure depuis le runner GitHub.

Trois pièges relevés le 28/07, tous vérifiés :

- un **403** sur `.gouv.fr`, Les Échos, 20 Minutes ou la Banque de France est
  un blocage WAF sur l'IP du runner, pas une mauvaise URL. Changer d'adresse
  n'y change rien : il faut remplacer la source ;
- un flux qui répond **200 avec 0 article** est le pire cas, parce qu'il est
  invisible dans les logs. Trois causes possibles, que seule l'inspection du
  contenu brut départage : page HTML servie à la place du flux, flux réellement
  vide, ou format non reconnu par le parseur (les flux **Atom** utilisent
  `<entry>` et non `<item>` — The Conversation était muette depuis son ajout) ;
- une source morte coûte jusqu'à **12 s de timeout par run** pour zéro article.

Enfin : élargir le vivier ne sert à rien si la matière n'entre pas dans le
prompt. Ce qui part au rédacteur est borné par `BUDGET_MATIERE`, et l'ordre
d'injection est décidé par la qualité de domaine puis par le juge de
pertinence. Une source de plus, mal classée, ne sera jamais lue.

## 9. Ce qui est en cours, et ce qu'il ne faut pas doubler

À la mi-août : la veille continue alimente la sélection (persistance des sujets
dans les fils, dédoublonnage par événement), un juge de pertinence des sources
tourne sur un petit modèle, et le chantier suivant est la QUALITÉ DE RÉDACTION
— deux tiers des articles publiés se répètent, et les détecteurs le voient sans
rien bloquer.

Une décision éditoriale reste ouverte et n'appartient à aucun agent : le
journal s'autorise-t-il à écrire qu'une affirmation publique n'est pas étayée
quand un organisme de vérification le dit ? Ne pas la trancher seul.
