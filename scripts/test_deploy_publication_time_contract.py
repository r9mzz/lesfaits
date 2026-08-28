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
    renormalize = 'scripts/normalize_sitemap_lastmod.py" --root /tmp/site'
    amend = 'git commit --amend --no-edit'
    slugs = 'git diff --name-only --diff-filter=A HEAD~1 HEAD -- articles/'
    push = 'git push'

    for token in (commit, stamp, site_dir, renormalize, amend, slugs, push):
        assert token in text, f"contrat de déploiement incomplet: {token!r} absent"

    i_commit = text.index(commit)
    i_stamp = text.index(stamp, i_commit)
    i_site = text.index(site_dir, i_stamp)
    i_renormalize = text.index(renormalize, i_site)
    i_amend = text.index(amend, i_renormalize)
    i_slugs = text.index(slugs, i_amend)
    i_push = text.index(push, i_slugs)

    assert i_commit < i_stamp < i_site < i_renormalize < i_amend < i_slugs < i_push, (
        "l'heure publique doit être scellée, puis le sitemap renormalisé contre "
        "l'état final, avant l'amendement, l'extraction des nouveaux articles et le push"
    )


def test_sitemap_est_renormalise_apres_estampillage() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    stamp = text.index('scripts/stamp_publication_times.py')
    normalize = text.index('scripts/normalize_sitemap_lastmod.py" --root /tmp/site', stamp)
    check = text.index('scripts/normalize_sitemap_lastmod.py" --root /tmp/site --check', normalize)
    amend = text.index('git commit --amend --no-edit', check)
    assert stamp < normalize < check < amend


def test_le_workflow_post_deploiement_n_est_pas_unique_barriere() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    block_start = text.index('cd /tmp/site')
    block = text[block_start:]
    assert 'scripts/stamp_publication_times.py' in block
    assert '--site-dir /tmp/site --previous-ref HEAD~1' in block


if __name__ == "__main__":
    test_horodatage_est_dans_le_checkout_public_avant_extraction_des_slugs()
    test_sitemap_est_renormalise_apres_estampillage()
    test_le_workflow_post_deploiement_n_est_pas_unique_barriere()
    print("OK: contrat d'horodatage du déploiement public")
