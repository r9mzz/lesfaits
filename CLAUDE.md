# Les Faits — lesfaits.info

## Test en cours (26-28/07, 2 jours, Nahil)

Guerre/faits-divers/politique retirés du rejet immédiat (`BLACKLIST` →
`_BLACKLIST_SUSPENDUE_TEST_2607` dans `pipeline.py`) : à voir si la charte
éditoriale (règles 1-15) et la vérification LLM (`sujet_sensible`) suffisent
à traiter ces sujets avec neutralité factuelle sans prise de parti, plutôt
que de les exclure a priori. Les garde-fous de sécurité légale (mineur
impliqué, affaire judiciaire en cours, diffamation) restent actifs sans
changement. Pas de retouche des catégories pour l'instant (un article CAN
féminine classé en "science" est un bug distinct à creuser séparément, pas
pendant ce test). **Si non concluant, remettre les mots-clés dans
`BLACKLIST`.**

## Philosophie éditoriale — priorité absolue

Le pipeline n'existe pas pour maximiser le nombre d'articles publiés. Il
existe pour **empêcher qu'un mauvais article soit publié**. Un run qui ne
publie rien parce que rien n'a passé les contrôles est un run réussi, pas un
échec. Ne jamais assouplir un garde-fou pour publier plus — le différenciateur
éditorial de Les Faits est un protocole de vérification transparent, pas le
volume de contenu.

Journal 100 % IA : génération d'articles ET vérification éditoriale 3 passes
sur Groq Llama 3.3 (3 clés en rotation — le compte Anthropic n'a plus de
crédits et ne sera pas réapprovisionné, décision de Nahil en juillet 2026 ;
quand Groq est en rate limit, on attend jusqu'à 8 cycles de 62 s plutôt que
de perdre le sujet). Site statique déployé sur GitHub Pages via le repo
`lesfaits-site`.

## Architecture

- `scripts/pipeline.py` — tout le pipeline : collecte RSS, scoring, génération,
  garde-fous déterministes, rendu HTML, index/feed/sitemap.
- `scripts/verification.py` — fact-check + correction (Groq Llama 3.3).
- Workflows : `pipeline.yml` (génération ~01h05/13h05 Paris, très en avance car
  les crons GitHub ont 1-4 h de retard), `deploy.yml` (mise en ligne ~07h/18h),
  `post_x.yml`, `newsletter.yml` (Brevo), `check_feeds.yml` (diagnostic RSS).
- **Un automate EXTERNE au dépôt** déclenche `pipeline.yml` à 15h00 et 15h50
  UTC et `deploy.yml` à 04h00 et 04h50 UTC, tous les jours à la minute près
  (constat 28/07, 5-6 jours consécutifs, en `workflow_dispatch` sur le compte
  de Nahil). Il n'est ni dans ce dépôt ni dans les Routines Claude — donc
  impossible à couper depuis le code. Ses effets sont neutralisés par deux
  garde-fous (`scripts/dernier_run.py`) : `pipeline.yml` ignore un
  `workflow_dispatch` démarrant moins de 2 h après le précédent — les deux
  crons du dépôt (matin + après-midi) ne sont JAMAIS filtrés, sinon un cron
  retardé par GitHub tombant après un déclenchement externe serait bloqué par
  lui et on perdrait le vrai run ; `deploy.yml` ignore
  un déploiement dont le SHA est déjà en ligne (critère de CONTENU, jamais de
  temps : ne jamais bloquer un déploiement qui a du neuf). Option `forcer`
  dans les deux cas. **À terme, il faut retrouver et couper cet automate.**
- Les articles affichent l'heure RÉELLE de génération (changement du 22/07,
  Nahil — avant cette date, l'heure affichée était arrondie au créneau
  07h00/18h00, jamais la génération technique ; ce n'est plus le cas).
- Après toute modif des templates : `python scripts/pipeline.py --rebuild`
  régénère index, catégories, archive, favoris, search.json, feed, sitemap.

## Charte éditoriale — règles INTANGIBLES

Ces règles sont codées dans les prompts (règles 11-15 du SYSTEM_PROMPT) ET dans
les garde-fous déterministes. Ne jamais les affaiblir ; toute modification des
prompts ou des garde-fous doit les préserver.

1. **Une idée = une seule apparition** dans tout l'article (résumé + faits +
   contexte + nuances). Plusieurs sources qui disent la même chose = UNE phrase
   de synthèse avec attribution groupée, jamais des reformulations successives.
2. **Rôle strict des sections** :
   - résumé (chapeau) : entrée DIRECTE dans le fait principal (chiffre, acteur,
     date) — jamais de phrase générique d'introduction ;
   - « Les faits » : uniquement les faits principaux du jour ;
   - « Contexte » : uniquement historique et mise en perspective — JAMAIS les
     faits du jour ni la méthodologie de l'étude ;
   - « Débats et nuances » : répond exclusivement à la question « Qu'est-ce
     qu'un lecteur devrait savoir avant de tirer une conclusion ? » — limites,
     incertitudes, désaccords, points non établis. JAMAIS de répétition d'un
     fait déjà présenté.
3. **Tribunes / prises de position** : tout l'article doit présenter le contenu
   comme les analyses et propositions de l'auteur (« estime », « plaide pour »,
   « propose »), signalé dès le titre — jamais comme des faits établis.
4. **Attributions** : max 7 « Selon X » par article, jamais deux phrases
   consécutives qui commencent ainsi, formes variées.
5. Chaque fait attribué doit figurer littéralement dans les sources fournies ;
   aucune extrapolation, aucun cadrage éditorial emprunté sans attribution.

6. **Titre** : factuel, neutre, 6-15 mots, jamais de vocabulaire putaclic
   (bizarre, insolite, choc…) ni de tournure en question.
7. **Longueur/sourcing minimum** : 500 mots sur chapeau+faits+contexte+nuances
   (avec une tolérance de 150 mots après relance d'étoffement, soit 350 mots
   acceptés au plancher — élargi de 400 à 350 le 20/07, Nahil), 3 sources
   minimum — un article qui n'atteint pas ce
   seuil après relance est rejeté définitivement, jamais publié incomplet.
8. **Angle éditorial obligatoire** : un sujet sans actualité identifiable, avec
   des sources trop pauvres pour l'expliquer, ou dont le contexte doit être
   rempli avec un fait divers sans rapport, n'est PAS publié — même si le texte
   est par ailleurs bien écrit. Mieux vaut publier moins d'articles que publier
   un sujet creux ou un cas médical sans diagnostic/mécanisme/évolution connus.
9. **Tournures génériques de remplissage** interdites sauf si elles apportent
   une information précise : « s'inscrit dans une dynamique », « constitue un
   enjeu majeur », « illustre la diversité des situations », « permet une
   plongée dans », « intervient dans un contexte où », « pourrait
   transformer », « reflète une évolution plus large ».
10. **Fusion des sources obligatoire** : si plusieurs sources rapportent
    exactement la même information, les fusionner en UNE phrase avec attribution
    groupée (« Selon Pressesante, Doctissimo et Futura Sciences, [fait] »). Une
    source ne justifie une phrase propre que si elle apporte une information
    DIFFÉRENTE. Ne jamais empiler une phrase par source pour le même fait.
11. **Contrôle qualité avant publication** — 7 critères non négociables. Tout
    article est refusé tant que l'un d'eux échoue :
    a) Chaque section remplit-elle UNIQUEMENT son rôle ?
    b) Une même idée apparaît-elle plusieurs fois ? → supprimer toutes les
       occurrences sauf la première.
    c) Chaque paragraphe apporte-t-il au moins une information nouvelle ?
    d) Le contexte aide-t-il à comprendre sans répéter les faits ?
    e) Débats et nuances = uniquement limites/incertitudes/désaccords, jamais
       les résultats principaux.
    f) Une phrase peut-elle être supprimée sans perte d'info ? → la supprimer.
    g) Plusieurs sources disent la même chose ? → les fusionner.

Garde-fous déterministes correspondants (déclenchent UNE relance corrective
combinée, jamais des relances en cascade — le quota Groq est la ressource rare) :
`attributions_fantomes`, `resume_repete_corps` (y compris répétitions internes
au chapeau), `faits_repetitifs` (intra ET inter-sections, 5-grammes),
`attributions_trop_repetitives`, `titre_de_mauvaise_qualite`, `cliches_ia`,
`intro_generique` (intros vagues sans information — déclenche correction),
`nuances_vagues` (généralités sans exemple concret dans « Débats et
nuances » — « les défis sont nombreux » sans chiffre ni fait précis qui
suit — retour revue éditoriale externe du 22/07), `affirmation_non_demontree`
(usage/potentiel présenté comme acquis — « ouvre de nouvelles perspectives »
— alors que la source ne décrit qu'un prototype/étude préliminaire/projet ;
doit être au conditionnel, même retour du 22/07).
Garde-fou séparé (non combiné, relance d'étoffement dédiée) :
`_deficit_longueur_sources` (500 mots cible / 350 mots plancher après
tolérance, 3 sources minimum — vérifier le compte de MOTS réel, jamais une
approximation en caractères).

Contrôle LLM (passe 2 de `verification.py`, indépendant des garde-fous
déterministes) : le fact-checker évalue aussi `angle_insuffisant` (le sujet
mérite-t-il un article ?) et `nature_contenu` (tribune/chronique/interview
doivent être signalées dès l'intro) — `angle_insuffisant: true` = rejet
définitif immédiat, jamais de tentative de correction (un sujet creux ne se
répare pas en réécrivant le texte).

## Quota Groq — fenêtre glissante, PAS un reset à minuit

Constat du 29/07, à démontrer avant toute remise en cause : le TPD Groq
(100 k tokens) est une **fenêtre glissante de 24 h**. Preuve — sur le run de
03h34 UTC, les délais « try again in… » renvoyés par Groq s'étalaient de 03h46
à 05h40 ; un reset quotidien les aurait tous groupés à 00h00. Deux
conséquences directes :

- **Les runs de l'après-midi amputent le budget du lendemain matin** (12 h plus
  tard, on est toujours dans la fenêtre). C'est ce qui a limité le run du 29/07
  à 1 article : les clés étaient déjà à 97 % consommées AVANT son démarrage
  (327 k tokens consommés par le run, ~1,07 M déjà comptabilisés sur les
  11 clés). D'où l'importance du garde-fou anti-run-rapproché.
- **Ne jamais abandonner un run sur « quota épuisé » sans regarder le délai
  annoncé** : le 29/07, une clé revenait dans 6 min 32 s et le run a rendu la
  main. `_delai_liberation()` extrait ce délai ; en dessous de
  `ATTENTE_MAX_LIBERATION` (15 min) le pipeline attend au lieu de perdre les
  sujets restants.

## Tunnel de sélection — mesures du 28/07 (27 runs)

623 candidats collectés → 319 générations tentées → **33 publiés (10 %)**.
Répartition des rejets : angle insuffisant 41, **troncature Groq 34**,
qualité des sources 30, sujet sensible 40, listicle 8, post-correction 12,
protocole (quota) 6. Autrement dit **~30 % des pertes ne sont PAS des
décisions éditoriales** mais des échecs techniques. Points à surveiller :

- **Troncature à max_tokens** : distribution bimodale — complétion médiane
  1 417 tokens, ou emballement du modèle jusqu'à la coupure. Donner plus de
  place ne fait pas converger (la relance à 6 000 ne sauvait que 11 % des
  cas, 4 sur 38) ; les 34 échecs restants brûlaient ~323 k tokens, soit
  3 quotas journaliers de clé, pour zéro article. Le contenu partiel est
  désormais récupéré (`_reparer_json_tronque`) plutôt que jeté.
- **Flux RSS morts** : 13 des ~41 sources renvoient 404/403/500 depuis le
  20/07 (elles ont été ajoutées sans être testées). Un flux mort est visible
  dans les logs (`[RSS ERREUR]`), mais un flux Atom lu comme du RSS ne l'est
  PAS : il renvoie 0 article en silence. Toujours vérifier le rendement réel
  d'une source, pas seulement l'absence d'erreur.
- **Le quota par catégorie borne la sélection AVANT `nb_max`** : avec
  6 catégories, `QUOTA_CATEGORIE = 3` plafonnait à 18 sujets quel que soit
  `nb_max`. Constat 29/07 : 655 articles collectés, 71 candidats… et exactement
  18 retenus, alors que `nb_max` valait 36. Porté à 6 par catégorie. Toute
  hausse de `nb_max` doit s'accompagner d'une hausse du quota, sinon elle
  n'a **aucun** effet.
- **Plafond par flux** (`MAX_ITEMS_PAR_FLUX`) : porté de 8 à 20 le 28/07. À 8,
  la collecte était bornée à ~230 articles/run avant tout filtre. Ce plafond ne
  coûte rien en quota Groq — il n'élargit que le vivier où
  `selectionner_meilleurs` puise ses `nb_max` sujets.

## Sources RSS — ne jamais en ajouter sans mesurer

`scripts/check_feeds.py` + le workflow `check_feeds.yml` (déclenchement manuel)
mesurent le rendement RÉEL de chaque flux depuis le runner GitHub — le sandbox
de développement n'a pas d'accès réseau vers ces domaines, une URL ne peut donc
PAS y être validée. Le script teste aussi des URLs candidates avant tout
rebranchement, et inspecte les flux qui répondent 200 avec 0 article.

État mesuré le 28/07 : **24 sources sur 40** produisaient des articles
(192 collectés) — la vague d'ajouts du 19/07 avait 13 flux morts sur 14,
ajoutés sans test. Après réparation : **36 sources sur 36, 635 articles
collectés**. Leçons :

- Un **403** sur `.gouv.fr`, Les Échos, 20 Minutes ou Banque de France est un
  blocage WAF sur l'IP du runner GitHub, pas une mauvaise URL : changer
  d'adresse n'y change rien, il faut remplacer la source.
- Une source morte coûte jusqu'à **12 s de timeout par run** (3 tentatives
  d'en-têtes), pour zéro article — les supprimer accélère la collecte.
- Un flux qui répond **200 avec 0 article** est le pire cas : invisible dans
  les logs. D'où le rapport `[RENDEMENT]` affiché à chaque run.
- Tout nouveau domaine doit être ajouté à `_DOMAINES_PRIMAIRES` ou
  `_DOMAINES_SECONDAIRES` — sinon il compte « tertiaire » et ne vaut rien pour
  la règle ≥1 primaire OU ≥2 secondaires, quel que soit son sérieux. Attention,
  ces listes sont distinctes de `_SOURCE_DOMAINS` (qui sert au choix d'image et
  aux droits voisins) : modifier l'une ne modifie pas l'autre.
- Trois causes distinctes derrière un « 200 avec 0 article », que l'inspection
  du contenu brut permet seule de départager : page HTML servie à la place du
  flux (Vie Publique, ANSES — supprimées), flux RSS valide mais réellement vide
  (ADEME — supprimée), ou format non reconnu par le parseur (The Conversation,
  Atom — réparée côté code).

## Pièges connus

- **Catégorie calculée sur l'extrait RSS et non sur l'article** (constat
  28/07 — Huawei/réseaux télécoms classé « science », CAN féminine classée
  « science ») : `detect_category` tournait sur le teaser RSS tronqué, qui
  ne contient presque aucun mot-clé propre au sujet ; le lexique « science »
  (plein de mots courants — « étude », « chercheurs », « scientifique »)
  raflait alors la mise, d'autant qu'il est 2e dans `_CAT_PRIORITE` et gagne
  les égalités. Trois correctifs : catégorie recalculée sur le TEXTE GÉNÉRÉ
  (titre + chapeau + faits + contexte), `_MOTS_FAIBLES` (mots peu
  discriminants comptés seulement dans le titre), et `SCORE_CATEGORIE_MIN`
  (en dessous de 2, on assume « societe » plutôt qu'un faux classement
  spécifique). Ne jamais reclasser depuis le seul extrait RSS.
- **Empilement « une phrase = une source »** (constat 28/07 sur l'article
  Huawei — 7 sources en 7 phrases quasi interchangeables dans « Les faits »,
  vu par le contrôle LLM mais classé « défaut de style non bloquant ») :
  `attributions_trop_repetitives` ne compte QUE les formes « Selon /
  D'après » — or la règle 4 encourage justement à varier les formes, donc un
  empilement en « indique X », « X rapporte », « X note » passait entre les
  mailles des deux garde-fous. Garde-fou dédié `sources_non_fusionnees`
  (règle 10) : ≥4 phrases consécutives attribuées chacune à une source
  DIFFÉRENTE → relance corrective combinée. Ne pas fusionner ce garde-fou
  avec celui de la règle 4, ils sanctionnent deux défauts opposés (répéter
  une forme / empiler des sources).
- **Flux Atom lus comme du RSS** (constat 28/07) : `fetch_rss` ne parcourait
  que les balises `<item>` (RSS). Atom utilise `<entry>`, dans un namespace —
  `root.iter("item")` n'y trouvait rien et la source renvoyait 0 article
  SANS erreur, en paraissant fonctionner dans les logs. The Conversation
  France (`articles.atom`) était muette depuis son ajout. Les entrées sont
  désormais repérées par leur nom de balise local, namespace ignoré.
- **Filtre anti-doublon trop agressif** (constat 28/07) : rejeter sur UN seul
  mot commun de 8 caractères n'a plus de sens une fois les mots tronqués à 8
  caractères pour absorber les variantes singulier/pluriel — « faire 8
  caractères » ne désigne plus un mot rare mais n'importe quel mot d'au moins
  8 lettres. Mesure sur les 129 titres publiés : 49 % se rejetaient
  mutuellement (« Huawei… » vs « Apple… **sécurité** », « médinas
  **historiques** » vs « chaleur **historique** », « CAN **féminine** » vs
  « douleurs **féminines** »). Il faut DEUX mots communs pour un rejet
  (15 %) ; un seul mot ne vaut qu'une rétrogradation (-25, pas -60 : à -60
  tout candidat sous 80 points passait sous le seuil de sélection, c'était un
  rejet déguisé). Ne jamais rejeter sur un seul mot commun.
- **Sourcing non revérifié après correction** (constat 28/07 — article Lidl
  publié avec 2 sources) : les deux contrôles de sourcing (règle 7, 3 sources
  minimum ; règle ≥1 primaire OU ≥2 secondaires) tournaient AVANT la passe de
  correction, qui réécrit aussi la liste des sources et peut en supprimer.
  Ils sont rejoués après correction. Tout contrôle placé avant
  `verifier_article` doit être considéré comme potentiellement invalidé par
  la passe 3.
- **Titre au futur pour un événement déjà survenu** (constat 28/07 sur
  l'article CXMT — titré « s'apprête à réaliser la plus grosse levée de
  fonds » alors que « Les faits » décrivent l'action déjà cotée, « a flambé
  de plus de 500 % lors de sa première journée ») : le pipeline agrège des
  sources publiées à des dates différentes ; quand le titre vient d'une
  dépêche pré-événement et le corps de dépêches post-événement, l'article
  annonce au futur ce qu'il raconte au passé. Garde-fou déterministe
  `incoherence_temporelle` + critère LLM `annonce_perimee` (bloquant après
  correction). Le même article cumulait une contradiction chiffrée non
  détectée (chapeau « 1 000 milliards de yuans » ≈ 120 Md€ vs faits
  « 450 milliards d'euros ») → `incoherence_inter_sections` renforcé sur la
  conversion d'unités/devises et sur deux valeurs divergentes du même chiffre.
- **Prise de position éditoriale** (constat 28/07 sur l'article Perenco/RDC —
  « Les autorités congolaises doivent prendre des mesures pour réguler les
  activités des entreprises pétrolières, comme le souligne Viralmag ») : le
  journal ne dit JAMAIS ce qu'un acteur devrait faire. Attribuer une injonction
  à une source ne la rend pas neutre — si une ONG réclame une mesure, l'écrire
  comme SA demande. Garde-fou `prise_de_position` sur le chapeau et « Débats et
  nuances » (5 % de déclenchement mesuré).
- **Chapeau répété dans « Débats et nuances »** : `resume_repete_corps` ne
  compare le chapeau qu'à « Les faits ». L'étendre à toutes les sections a été
  TESTÉ puis écarté (28/07) — le taux passait de 7 % à 41-95 % selon la
  métrique, car un chapeau partage forcément des groupes de mots avec le corps
  qu'il résume (noms propres, termes techniques). Aucun seuil ne sépare le
  résumé légitime du recopiage ; ce défaut relève du contrôle LLM
  (`redondance`), pas d'un garde-fou déterministe.
- **Précision > rappel sur les garde-fous à relance** : le quota Groq est la
  ressource rare et chaque garde-fou déclenche une relance corrective. Motif
  « il est important de noter/souligner que… » testé puis ÉCARTÉ de
  `cliches_ia` (28/07) : même restreint aux phrases sans chiffre, il faisait
  passer le déclenchement de 4 % à 42 % du corpus — c'est un connecteur
  français courant, pas un défaut. Toujours mesurer le taux de déclenchement
  sur les articles publiés avant d'ajouter un motif.
- **Listicles commerciaux déguisés** (constat 26/07 — « Lidl : 5 appareils de
  cuisine à moins de 10 euros » publié, lu comme une pub) : `_COMMERCE_RE`
  élargi à « (à) moins de X€ » et aux enseignes discount (Lidl, Aldi, Action)
  en plus de la liste existante — un article n'est pas éditorial simplement
  parce qu'il cite un prix bas, il l'est encore moins avec une enseigne.
- **Doublon de sujet malgré la fenêtre anti-doublon** (constat 26/07 — deux
  articles publiés à 5 h d'intervalle sur la même découverte de carie
  néandertalienne) : le filtre de récurrence dans `score_editorial` comparait
  des mots exacts (« néandertaliens » ≠ « néandertalien », singulier/pluriel
  selon la source RSS) et ne détectait aucun chevauchement. Comparaison
  passée à un préfixe de 8 caractères (accents retirés) plutôt qu'au mot
  exact — ne jamais revenir à une correspondance de mot strict.
- **Image hero hors-sujet sur un article genré** (constat 26/07 — photo de
  joueurs de football HOMMES sur un article « CAN féminine 2026 ») :
  `extract_visual_keywords` ne précisait pas le genre à Pexels, qui renvoie du
  stock majoritairement masculin par défaut sur les requêtes sport neutres.
  Prompt LLM + garde-fou déterministe (regex « féminin(e)/femmes/dames » dans
  le titre → force « women » dans les mots-clés si absent) ajoutés dans
  `extract_visual_keywords`.
- **Sources marchandes interdites** : Amazon, Fnac, Payot, Cultura, réseaux
  sociaux, plateformes d'avis ne sont JAMAIS des sources citables (« Selon
  Amazon » a été publié le 15/07 — trois fiches produit du même livre
  comptées comme trois sources). Blocklist `_DOMAINES_NON_CITABLES_RE` +
  filtre `_est_source_citables()` appliqués dans `duckduckgo_search` ET à la
  vérification des sources ; dédup par titre normalisé (même œuvre/dépêche
  sur plusieurs sites = UNE source). Ne jamais retirer ces filtres.
- **Hiérarchie de sources en liste BLANCHE** (`qualite_source`,
  `bilan_qualite_sources`) : primaire (institutions/gouvernements/revues à
  comité de lecture) / secondaire (agences de presse, médias de référence) /
  tertiaire (vulgarisation, Wikipédia — jamais une preuve) / interdite
  (marchands, réseaux sociaux). Règle de publication : **≥1 source primaire
  OU ≥2 sources secondaires indépendantes**, sinon rejet — un empilement de
  tertiaires ne suffit jamais. Une blocklist seule ne suffit pas (elle
  grandit indéfiniment) ; c'est la liste blanche qui doit primer.
- **Protocole de vérification jamais optionnel** : si le fact-check LLM
  échoue (rate limit, erreur API — statut `erreur_verification` ou
  `non_verifie`), l'article n'est PAS publié, même s'il est par ailleurs bon.
  Le sujet est retenté au run suivant. Ne jamais publier « par défaut » faute
  de vérification complète.
- Le différenciateur éditorial n'est PAS un compteur de sources qualifiées
  dans les méta (badges PRIMAIRE/MÉDIA/CONTEXTE testés puis retirés le
  15/07 sur retour utilisateur) mais la section **« Pourquoi cet article a
  été publié »** en bas de chaque article (`art__pourquoi` dans
  `build_article_html`) : explique en langage clair — pas en indicateurs
  techniques — la répartition des sources par fiabilité, la règle de
  publication appliquée, le résultat du fact-check, et le rappel qu'il n'y a
  jamais de relecture humaine. C'est l'argument de marque du site ("on ne
  vous demande pas de nous croire, on vous montre pourquoi cet article a
  été publié") — à préserver dans tout futur design, ne jamais le réduire à
  un badge ou un score.
- Le HTML des articles déjà publiés N'EST PAS régénéré par
  `pipeline.py --rebuild` (qui ne touche qu'index/catégories/archive/
  sitemap) : toute évolution du template `build_article_html` nécessite un
  patch rétroactif dédié (script ponctuel, non versionné) pour s'appliquer
  aux articles existants.

- Les objets `sources` renvoyés par le correcteur LLM peuvent être incomplets :
  tout accès direct `s["titre"]` / `s["institution"]` au rendu est interdit —
  utiliser `.get()` avec repli (un KeyError ici coûte un article entier).
- `positions` (spectre) : le LLM renvoie parfois `null` — `.get(clé, défaut)`
  ne remplace PAS un null existant, utiliser `or`.
- Images : chaque JPEG doit avoir ses variantes `.webp` et `-480.webp`
  (générées par `_ensure_webp_variants` à chaque rebuild) — les templates
  servent du WebP ; JPEG réservé à og:image, RSS, newsletter.
- Contraste : petits textes bleus en `--blue-ink` (AA), jamais `--blue`.
- Flux RSS capricieux (415 INSERM, 406 The Conversation, XML cassé ANSES) :
  échelle de 3 tentatives + reparse lxml recover dans `fetch_rss`.
- La clé Brevo ne doit JAMAIS être injectée dans le HTML client (fuite corrigée
  en juillet 2026 — formulaire hébergé Brevo uniquement).

## Git

- Branche de travail : `claude/morning-run-verification-r7khv1`, merge dans
  `main` pour mettre en production (le pipeline et le déploiement tournent sur main).
- Les fichiers générés (articles/, index.html, feed.xml, data/*.json…) sont
  commités par le bot à chaque run : en cas de conflit sur ces fichiers, prendre
  la version de main puis relancer `--rebuild`.
