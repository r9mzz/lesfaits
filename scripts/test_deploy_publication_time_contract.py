# -*- coding: utf-8 -*-
"""Contrat: le déploiement scelle les heures publiques avant le push."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


def test_horodatage_est_dans_le_checkout_public_avant_extraction_des_slugs() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    commit = 'git commit -m "$MESSAGE"'
    stamp = 'scripts/stamp_publication_times.py'
    site_dir = '--site-dir /tmp/site --previous-ref HEAD~1'
    feed_normalize = 'scripts/normalize_feed_pubdates.py" --root /tmp/site'
    renormalize = 'scripts/normalize_sitemap_lastmod.py" --root /tmp/site --baseline-ref HEAD~1'
    final_guard = 'git diff --cached --quiet HEAD~1'
    amend = 'git commit --amend --no-edit'
    slugs = 'git diff --name-only --diff-filter=A HEAD~1 HEAD -- articles/'
    push = 'git push'
    for token in (commit, stamp, site_dir, feed_normalize, renormalize, final_guard, amend, slugs, push):
        assert token in text, f"contrat de déploiement incomplet: {token!r} absent"
    positions = [text.index(commit), text.index(stamp, text.index(commit)), text.index(site_dir, text.index(stamp)), text.index(feed_normalize, text.index(site_dir)), text.index(renormalize, text.index(feed_normalize)), text.index(final_guard, text.index(renormalize)), text.index(amend, text.index(final_guard)), text.index(slugs, text.index(amend)), text.index(push, text.index(slugs))]
    assert positions == sorted(positions)


def test_sitemap_est_renormalise_apres_estampillage() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    stamp = text.index('scripts/stamp_publication_times.py')
    normalize_token = 'scripts/normalize_sitemap_lastmod.py" --root /tmp/site --baseline-ref HEAD~1'
    check_token = 'scripts/normalize_sitemap_lastmod.py" --root /tmp/site --baseline-ref HEAD~1 --check'
    normalize = text.index(normalize_token, stamp)
    check = text.index(check_token, normalize + len(normalize_token))
    guard = text.index('git diff --cached --quiet HEAD~1', check)
    amend = text.index('git commit --amend --no-edit', guard)
    assert stamp < normalize < check < guard < amend


def test_rss_est_renormalise_apres_estampillage() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    stamp = text.index('scripts/stamp_publication_times.py')
    normalize_token = 'scripts/normalize_feed_pubdates.py" --root /tmp/site'
    check_token = 'scripts/normalize_feed_pubdates.py" --root /tmp/site --check'
    normalize = text.index(normalize_token, stamp)
    check = text.index(check_token, normalize + len(normalize_token))
    sitemap = text.index('scripts/normalize_sitemap_lastmod.py" --root /tmp/site --baseline-ref HEAD~1', check)
    assert stamp < normalize < check < sitemap


def test_un_lot_finalement_identique_est_abandonne_sans_amend_vide() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    guard = text.index('if git diff --cached --quiet HEAD~1; then')
    reset = text.index('git reset --hard HEAD~1', guard)
    stop = text.index('exit 0', reset)
    amend = text.index('git commit --amend --no-edit', stop)
    assert guard < reset < stop < amend


def test_le_workflow_post_deploiement_n_est_pas_unique_barriere() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    block = text[text.index('cd /tmp/site'):]
    assert 'scripts/stamp_publication_times.py' in block
    assert '--site-dir /tmp/site --previous-ref HEAD~1' in block
    assert block.count('--baseline-ref HEAD~1') >= 2


if __name__ == "__main__":
    test_horodatage_est_dans_le_checkout_public_avant_extraction_des_slugs()
    test_sitemap_est_renormalise_apres_estampillage()
    test_rss_est_renormalise_apres_estampillage()
    test_un_lot_finalement_identique_est_abandonne_sans_amend_vide()
    test_le_workflow_post_deploiement_n_est_pas_unique_barriere()
    print("OK: contrat d'horodatage du déploiement public")
