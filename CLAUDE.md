# Les Faits — lesfaits.info

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
  `post_x.yml`, `newsletter.yml` (Brevo).
- Les articles affichent l'heure du CRÉNEAU de mise en ligne (07h00/18h00),
  jamais l'heure technique de génération.
- Après toute modif des templates : `python scripts/pipeline.py --rebuild`
  régénère index, catégories, archive, favoris, search.json, feed, sitemap.

## Charte éditoriale — règles INTANGIBLES

Ces règles sont codées dans les prompts (règles 21-23 du SYSTEM_PROMPT) ET dans
les garde-fous déterministes. Ne jamais les affaiblir ; toute modification des
prompts ou des garde-fous doit les préserver.

1. **Une idée = une seule apparition** dans tout l'article (résumé + faits +
   contexte + nuances). Plusieurs sources qui disent la même chose = UNE phrase
   de synthèse avec attribution groupée, jamais des reformulations successives.
2. **Rôle strict des sections** :
   - résumé (chapeau) : présentation rapide du sujet ;
   - « Les faits » : uniquement les faits principaux du jour ;
   - « Contexte » : uniquement ce qui permet de COMPRENDRE les faits, sans les répéter ;
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
7. **Longueur/sourcing minimum** : 700 mots sur faits+contexte+nuances (avec
   une tolérance de 100 mots après relance d'étoffement, soit 600 mots
   acceptés au plancher), 3 sources minimum — un article qui n'atteint pas ce
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

Garde-fous déterministes correspondants (déclenchent UNE relance corrective
combinée, jamais des relances en cascade — le quota Groq est la ressource rare) :
`attributions_fantomes`, `resume_repete_corps` (y compris répétitions internes
au chapeau), `faits_repetitifs` (intra ET inter-sections, 5-grammes),
`attributions_trop_repetitives`, `titre_de_mauvaise_qualite`, `cliches_ia`.
Garde-fou séparé (non combiné, relance d'étoffement dédiée) :
`_deficit_longueur_sources` (700 mots cible / 600 mots plancher après
tolérance, 3 sources minimum — vérifier le compte de MOTS réel, jamais une
approximation en caractères).

Contrôle LLM (passe 2 de `verification.py`, indépendant des garde-fous
déterministes) : le fact-checker évalue aussi `angle_insuffisant` (le sujet
mérite-t-il un article ?) et `nature_contenu` (tribune/chronique/interview
doivent être signalées dès l'intro) — `angle_insuffisant: true` = rejet
définitif immédiat, jamais de tentative de correction (un sujet creux ne se
répare pas en réécrivant le texte).

## Pièges connus

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
