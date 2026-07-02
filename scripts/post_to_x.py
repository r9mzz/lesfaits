"""
Les Faits — Publication automatique des nouveaux articles sur X (Twitter)
==========================================================================
Appelé par deploy.yml après chaque publication, avec en argument le fichier
listant les slugs des articles ajoutés lors de ce déploiement (un par ligne).

Poste au maximum MAX_POSTS_PAR_RUN tweets par exécution (2 déploiements/jour
=> ~8 posts/jour max, largement sous le quota gratuit de l'API X, 500/mois).

Clés attendues dans l'environnement (secrets GitHub Actions, jamais en dur) :
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
Sans ces clés, le script s'arrête proprement (aucun impact sur le déploiement).
"""

import os, sys, json, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
INDEX_JSON = ROOT / "data" / "articles.json"
BASE_URL = "https://lesfaits.info"

MAX_POSTS_PAR_RUN = 4

CAT_HASHTAGS = {
    "societe": "#Société", "science": "#Science", "economie": "#Économie",
    "tech": "#Tech", "sante": "#Santé", "environnement": "#Environnement",
}


def main():
    keys = [os.getenv(k, "") for k in
            ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")]
    if not all(keys):
        print("[X] Clés API absentes — publication X désactivée (rien à faire)")
        return

    if len(sys.argv) < 2 or not Path(sys.argv[1]).exists():
        print("[X] Pas de fichier de nouveaux articles — rien à publier")
        return

    slugs = [l.strip() for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not slugs:
        print("[X] Aucun nouvel article dans ce déploiement")
        return

    articles = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    by_slug = {a["slug"]: a for a in articles}
    # Ordre de l'index = plus récent d'abord ; on poste les plus importants
    ordered = [a for a in articles if a["slug"] in set(slugs)][:MAX_POSTS_PAR_RUN]

    import tweepy
    client = tweepy.Client(
        consumer_key=keys[0], consumer_secret=keys[1],
        access_token=keys[2], access_token_secret=keys[3],
    )

    for art in ordered:
        url = f"{BASE_URL}/articles/{art['slug']}.html"
        tag = CAT_HASHTAGS.get(art.get("categorie", ""), "")
        # 280 chars max ; une URL compte pour 23. Marge : titre tronqué à 200.
        titre = art["titre"][:200]
        text = f"{titre}\n\n{url}\n\n{tag} #LesFaits".strip()
        try:
            resp = client.create_tweet(text=text)
            print(f"[X] ✓ posté : {art['slug']} (id {resp.data['id']})")
        except Exception as e:
            # Un échec de tweet ne doit jamais faire échouer le déploiement
            print(f"[X] ✗ échec {art['slug']} : {e}")
        time.sleep(3)

    skipped = len(slugs) - len(ordered)
    if skipped > 0:
        print(f"[X] {skipped} article(s) non postés (cap {MAX_POSTS_PAR_RUN}/run pour rester sous le quota gratuit)")


if __name__ == "__main__":
    main()
