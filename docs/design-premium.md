# Les Faits — Design Premium 2026

Le redesign est volontairement isolé de la feuille historique.

## Activer / désactiver

Le fichier `data/premium-design.json` contient l'interrupteur `enabled`.

- `true` : le déploiement injecte `/src/premium.css?v=1` et les métadonnées app.
- `false` : le déploiement retire uniquement les éléments marqués `data-lf-premium`, `data-lf-app` et `data-lf-app-manifest`.

Le HTML et le CSS historiques ne sont pas réécrits par cette couche. Le retour au rendu précédent ne dépend donc pas d'une reconstruction manuelle des anciennes règles.

## Compatibilité app

La couche ajoute les safe areas iOS, les tailles tactiles, le mode `display-mode: standalone`, les couleurs de barre système clair/sombre et conserve le manifest existant.

## Garde-fous

`scripts/test_premium_design.py` vérifie notamment :

- l'idempotence de l'application ;
- le retrait complet de la couche ;
- la restauration exacte d'un document déjà muni de son manifest ;
- la présence des règles mobile/app essentielles ;
- l'équilibre syntaxique des accolades CSS.
