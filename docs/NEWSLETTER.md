# Newsletter Les Faits

## Architecture

Le formulaire public est servi par Les Faits mais l'inscription, le double
opt-in, la conservation des contacts et le désabonnement sont traités par
Brevo. Aucune clé API n'est exposée dans le navigateur.

`src/newsletter.js` collecte l'adresse, la fréquence et les rubriques choisies.
La réponse du formulaire hébergé est opaque au navigateur : le site confirme
donc uniquement que la demande a été transmise, jamais que Brevo l'a acceptée.
L'inscription devient active après le clic dans l'email de confirmation.

Le digest est lancé **après un déploiement public réussi**, et non à une heure
fixe indépendante. Les lecteurs ne reçoivent ainsi pas de lien vers un article
encore absent du site.

## Lot réellement publié

La matière d'une newsletter automatique ne dépend plus de l'heure technique de
génération dans le dépôt source. Le workflow ouvre le commit du dépôt public
`lesfaits-site` qui porte le créneau `07h00` ou `18h00`, puis extrait uniquement
les fichiers `articles/*.html` réellement **ajoutés par ce commit**.

Cette liste fermée est enregistrée dans `newsletter-slugs.txt`, validée avant
tout appel Brevo, puis transmise au moteur. Une redirection de consolidation
`noindex` est ignorée ; une vraie page ajoutée qui manquerait dans
`data/search.json` bloque l'envoi au lieu de disparaître silencieusement.

Ce mécanisme couvre notamment les crons GitHub retardés : un article généré
plus tôt mais publié seulement au déploiement suivant reste inclus dans le bon
digest.

## Attributs Brevo

Le script valide et crée automatiquement les attributs manquants :

| Attribut | Type | Valeurs |
|---|---|---|
| `FREQ` | texte | `morning`, `evening`, `both` |
| `CAT_SOCIETE` | booléen | vrai/faux |
| `CAT_SCIENCE` | booléen | vrai/faux |
| `CAT_ECONOMIE` | booléen | vrai/faux |
| `CAT_TECH` | booléen | vrai/faux |
| `CAT_SANTE` | booléen | vrai/faux |
| `CAT_ENVIRONNEMENT` | booléen | vrai/faux |

`ENVOI_MATIN` reste lu uniquement pour les anciens contacts. Un contact sans
fréquence moderne ni valeur historique reçoit les deux éditions.

## Listes

- `BREVO_LIST_ID` : liste principale des abonnés confirmés.
- `Digest — Envoi du jour` : liste technique permanente, créée automatiquement.

La liste technique n'est jamais vidée brutalement. Le script calcule les
ajouts/retraits, attend la fin des opérations Brevo, contrôle les échecs
partiels puis relit la liste. Les contacts désabonnés de cette liste sont
conservés afin de préserver leur choix et sont exclus de chaque audience.

## Idempotence

Le nom d'une campagne automatique contient la date, le créneau et les douze
premiers caractères du commit public. Une relance du même déploiement ne peut
pas renvoyer la campagne, tandis que deux vrais déploiements distincts le même
jour et sur le même créneau restent distinguables.

Pendant la migration, une ancienne campagne nommée seulement par date/créneau
est reconnue comme équivalente si son envoi a suivi immédiatement ce même
commit public. Le dernier digest de l'ancien moteur (`nl-digest`) reste aussi
pris en compte pour ne pas renvoyer l'historique lors du premier passage en v2.

## Contrôles

```bash
python -m py_compile \
  scripts/generer_digest.py \
  scripts/run_newsletter.py \
  scripts/harden_newsletter.py \
  scripts/test_newsletter.py \
  scripts/test_run_newsletter.py \
  scripts/test_newsletter_campaigns.py
python scripts/test_newsletter.py
python scripts/test_run_newsletter.py
python scripts/test_newsletter_campaigns.py
node --check src/newsletter.js
python scripts/harden_newsletter.py --check
```

Validation de la configuration Brevo sans campagne :

```bash
python scripts/run_newsletter.py --check-config
```

Aperçu local sans secret, sans appel Brevo, sans modification de contact et
sans envoi :

```bash
python scripts/run_newsletter.py --slot matin --dry-run
```

Aperçu d'un lot public exact :

```bash
python scripts/run_newsletter.py \
  --slot matin \
  --now 2026-08-07T07:00:00+02:00 \
  --slugs-file newsletter-slugs.txt \
  --dry-run
```

Le workflow conserve pendant 14 jours `newsletter-preview.html`,
`newsletter-slugs.txt` et le journal d'exécution.

## Secrets GitHub

- `BREVO_API_KEY`
- `BREVO_LIST_ID`
- `BREVO_SENDER_EMAIL`
- `SITE_DEPLOY_TOKEN`

La page de confirmation et la page de désabonnement personnalisées doivent
rester configurées dans le tableau de bord Brevo avec les URL publiques
`/confirmation.html` et `/desabonnement.html`.
