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

Le nom d'une campagne contient la date et le créneau. Une campagne déjà envoyée,
mise en file ou programmée ne peut pas être renvoyée par une relance du workflow.

Les articles sont sélectionnés depuis le dernier digest réellement envoyé, avec
un repli de 30 heures lors du premier lancement. Seuls les fichiers `articles/`
ajoutés par Git sont pris en compte.

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

Le workflow conserve pendant 14 jours `newsletter-preview.html` et le journal
d'exécution.

## Secrets GitHub

- `BREVO_API_KEY`
- `BREVO_LIST_ID`
- `BREVO_SENDER_EMAIL`
- `SITE_DEPLOY_TOKEN`

La page de confirmation et la page de désabonnement personnalisées doivent
rester configurées dans le tableau de bord Brevo avec les URL publiques
`/confirmation.html` et `/desabonnement.html`.
