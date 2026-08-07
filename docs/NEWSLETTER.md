# Newsletter Les Faits

## Architecture

Le formulaire public est servi par Les Faits mais l'inscription, le double
opt-in, la conservation des contacts et le désabonnement sont traités par
Brevo. Aucune clé API n'est exposée dans le navigateur.

`src/newsletter.js` transmet uniquement l'adresse email et le marqueur attendu
par le formulaire Brevo réellement publié. La réponse cross-origin est opaque :
le site confirme donc que la demande a été transmise, jamais que Brevo a accepté
l'adresse. L'inscription devient active après le clic dans l'email de
confirmation.

Le digest est lancé **après un déploiement public réussi**, et non à une heure
fixe indépendante. Les lecteurs ne reçoivent ainsi pas de lien vers un article
encore absent du site.

## Préférences et comportement par défaut

L'audit réel du formulaire hébergé a établi qu'il ne collecte pas `FREQ` ni les
six champs `CAT_*`. Les anciens contrôles de fréquence et de rubriques ont donc
été retirés du formulaire Les Faits : ils affichaient une personnalisation que
Brevo n'enregistrait pas.

Une nouvelle inscription reçoit désormais le comportement réellement garanti :

- éditions du matin et du soir ;
- uniquement lorsqu'un déploiement contient de nouveaux articles ;
- toutes les rubriques présentes dans ce lot.

Les contacts plus anciens qui possèdent déjà des attributs `FREQ`, `CAT_*` ou
`ENVOI_MATIN` explicites conservent leurs préférences : le moteur continue de
les lire. Ces choix ne reviendront dans le formulaire public que lorsque le
formulaire Brevo publié les exposera effectivement et que l'audit le confirmera.

## Contrat du formulaire Brevo

`scripts/audit_brevo_form.py` télécharge uniquement la page publique, sans
soumettre d'adresse, et contrôle qu'elle reste accessible, en POST, avec les
champs minimaux `EMAIL` et `LESFAITS_VERIFICATION`.

Ce contrôle tourne sur chaque PR newsletter, avant chaque campagne et lors de
la vérification de configuration Brevo. Une dérive externe bloque l'envoi avec
un diagnostic précis au lieu de créer silencieusement des inscriptions
incomplètes.

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

## Attributs historiques Brevo

Le script conserve et valide les attributs utilisés par les anciens contacts :

| Attribut | Type | Valeurs |
|---|---|---|
| `FREQ` | texte | `morning`, `evening`, `both` |
| `CAT_SOCIETE` | booléen | vrai/faux |
| `CAT_SCIENCE` | booléen | vrai/faux |
| `CAT_ECONOMIE` | booléen | vrai/faux |
| `CAT_TECH` | booléen | vrai/faux |
| `CAT_SANTE` | booléen | vrai/faux |
| `CAT_ENVIRONNEMENT` | booléen | vrai/faux |

`ENVOI_MATIN` reste lu pour la compatibilité avec les contacts encore plus
anciens. Un contact sans préférence explicite reçoit les deux éditions et
toutes les rubriques.

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
  scripts/harden_newsletter_v3.py \
  scripts/audit_brevo_form.py \
  scripts/test_newsletter.py \
  scripts/test_run_newsletter.py \
  scripts/test_newsletter_campaigns.py \
  scripts/test_harden_newsletter_v3.py \
  scripts/test_audit_brevo_form.py
python scripts/test_newsletter.py
python scripts/test_run_newsletter.py
python scripts/test_newsletter_campaigns.py
python scripts/test_harden_newsletter_v3.py
python scripts/test_audit_brevo_form.py
python scripts/audit_brevo_form.py
node --check src/newsletter.js
python scripts/harden_newsletter_v3.py --check
```

Validation de la configuration Brevo sans campagne :

```bash
python scripts/run_newsletter.py --check-config
python scripts/audit_brevo_form.py
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
