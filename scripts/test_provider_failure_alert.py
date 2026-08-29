from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pipeline.yml"


def test_provider_alert_covers_preflight_permanent_failure():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "toutes les clés refusées par erreur permanente" in text
    assert "401|402|403|404|429" in text


if __name__ == "__main__":
    test_provider_alert_covers_preflight_permanent_failure()
    print("OK — provider failure alert")
