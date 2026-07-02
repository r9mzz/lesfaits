# Les Faits — pipeline éditorial

Dépôt privé : génération des articles, données et gabarits HTML. Le dépôt public
[`lesfaits-site`](https://github.com/r9mzz/lesfaits-site) (GitHub Pages, domaine
`lesfaits.info`) est un simple miroir déployé automatiquement — ne jamais éditer
`lesfaits-site` directement pour un changement durable : il sera écrasé au
prochain déploiement (`deploy.yml`, 2x/jour).

## Base path

Le domaine custom `lesfaits.info` sert le site à la racine. Toute page générée
doit donc utiliser :

- `<base href="/"/>`
- `BASE_URL = "https://lesfaits.info"` (défini dans `scripts/pipeline.py`)

Ne jamais générer `/lesfaits/` ou `/lesfaits-site/` (ancien chemin GitHub Pages
avant l'achat du domaine) dans les liens, `og:url`, `canonical`, JSON-LD,
manifest, ou favicon. `scripts/_patch_static.py` / le rebuild de `pipeline.py`
sont la source de vérité pour ces valeurs.

## Pipeline de publication (deux étages)

1. **`pipeline.yml`** (cron ~01h35/~10h35 Paris) — génère les brouillons via
   Groq, commit dans ce dépôt privé uniquement (pas de publication).
2. **`deploy.yml`** (cron ~07h/~18h Paris) — reconstruit index/archives/catégories
   (`pipeline.py --rebuild`), patch les articles (`patch_articles.py`), puis
   copie tout vers `lesfaits-site` en un seul commit. C'est pour ça que
   plusieurs articles générés à des heures différentes affichent le même
   horodatage "07h00"/"18h00" — c'est l'heure de publication du lot, pas de
   génération individuelle.

**Limite connue** : les crons GitHub Actions ne sont pas garantis à l'heure —
retards de 1 à 4h fréquents, voire créneaux entièrement sautés (constaté le
02/07/2026 sur le deploy de 07h). Les horaires ci-dessus sont donc des cibles
avec une marge intégrée : la génération part très en avance pour être toujours
prête, le déploiement vise 10 min avant l'heure de publication. Si un créneau
saute, relancer `deploy.yml` à la main (onglet Actions → Run workflow). Pour
une exactitude stricte, il faudrait un déclencheur externe (ex. cron-job.org →
`workflow_dispatch` via l'API GitHub avec un token).

Après toute correction manuelle du contenu déployé (`lesfaits-site`), pensez à
répercuter le même correctif ici — sinon le prochain déploiement planifié
l'efface silencieusement.

## Statut du pipeline IA

Génération actuelle : Groq (`llama-3.3-70b-versatile`). Un pipeline de
vérification en 3 passes (génération → détection de sources non vérifiées →
correction automatique) via l'API Anthropic est prévu mais **en attente d'une
clé `ANTHROPIC_API_KEY`** à ajouter comme secret GitHub Actions avant
implémentation.
