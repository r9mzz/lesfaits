"""Contrat CI du garde des reproches auto-contradictoires."""
from pathlib import Path

WORKFLOW = Path('.github/workflows/verification-provider-ci.yml')
TEST = 'scripts/test_juge_reproche_auto_contredit.py'
SELF = 'scripts/test_juge_reproche_auto_contredit_ci_contract.py'


def main():
    text = WORKFLOW.read_text(encoding='utf-8')
    assert text.count(TEST) >= 3, (
        'Le test du garde doit être présent dans les paths, la compilation et l’exécution CI.'
    )
    assert text.count(SELF) >= 3, (
        'Le test de contrat doit lui-même déclencher, compiler et s’exécuter en CI.'
    )
    print('Contrat CI reproches auto-contradictoires: OK')


if __name__ == '__main__':
    main()
