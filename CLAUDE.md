# Les Faits — lesfaits.info

Journal 100 % IA : génération d'articles (Groq Llama 3.3, fallback Anthropic Haiku),
vérification éditoriale 3 passes (Anthropic Sonnet), site statique déployé sur
GitHub Pages via le repo `lesfaits-site`.

## Architecture

- `scripts/pipeline.py` — tout le pipeline : collecte RSS, scoring, génération,
  garde-fous déterministes, rendu HTML, index/feed/sitemap.
- `scripts/verification.py` — fact-check + correction (Anthropic).
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

Garde-fous déterministes correspondants (déclenchent UNE relance corrective
combinée, jamais des relances en cascade — le quota Groq est la ressource rare) :
`attributions_fantomes`, `resume_repete_corps` (y compris répétitions internes
au chapeau), `faits_repetitifs` (intra ET inter-sections, 5-grammes),
`attributions_trop_repetitives`.

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
