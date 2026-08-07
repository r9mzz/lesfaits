# -*- coding: utf-8 -*-
"""Construit un rapport compact et fiable à partir des logs du pipeline."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ATTEMPT_RE = re.compile(r"^\s*→\s+Génération\s+\[", re.M)
FINAL_RE = re.compile(r"Terminé\s+—\s+(\d+)\s+article\(s\)\s+publié\(s\)", re.I)
REJECTION_RE = re.compile(
    r"^\s*\[(REJET(?:\s+[^\]]+)?|REJET VITRINE|REJET QUALITÉ|REJET SOURCES|"
    r"REJET PROTOCOLE|REJET POST-CORRECTION)\]\s*(.+)$",
    re.M,
)
ERROR_RE = re.compile(r"^\s*(?:\[(?:ERREUR|FATAL)[^\]]*\]|::error::)\s*(.+)$", re.M | re.I)
ACCEPTED_RE = re.compile(r"\[VITRINE\]\s*✓\s*article admis", re.I)
QUOTA_LINE_RE = re.compile(
    r"^.*(?:quota|rate limit|rate_limit|lib[ée]ration|TPD|attente \d+).*$",
    re.M | re.I,
)
QUOTA_STOP_RE = re.compile(r"\[ARR[ÊE]T\].*quota Groq", re.I)
DRY_RUN_RE = re.compile(r"\(dry-run\)|--dry-run", re.I)


def _clean_reason(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value[:240]


def summarize_text(text: str) -> dict:
    text = text or ""
    attempts = len(ATTEMPT_RE.findall(text))
    accepted = len(ACCEPTED_RE.findall(text))
    final_match = FINAL_RE.search(text)
    final_count = int(final_match.group(1)) if final_match else accepted

    rejection_rows = [
        (_clean_reason(kind), _clean_reason(reason))
        for kind, reason in REJECTION_RE.findall(text)
    ]
    rejection_reasons = Counter(reason for _, reason in rejection_rows if reason)
    errors = [_clean_reason(item) for item in ERROR_RE.findall(text)]
    quota_lines = [_clean_reason(item) for item in QUOTA_LINE_RE.findall(text)]
    quota_stop = bool(QUOTA_STOP_RE.search(text))
    dry_run = bool(DRY_RUN_RE.search(text))

    if dry_run:
        status = "dry_run"
    elif errors:
        status = "technical_failure"
    elif final_count > 0 or accepted > 0:
        status = "published"
    elif quota_stop or quota_lines:
        status = "empty_quota"
    elif attempts > 0 or rejection_rows:
        status = "empty_editorial"
    else:
        status = "empty_unknown"

    return {
        "status": status,
        "attempts": attempts,
        "accepted_showcase": accepted,
        "final_publications": final_count,
        "rejections": len(rejection_rows),
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_reasons.most_common(10)
        ],
        "quota_events": len(quota_lines),
        "quota_stopped_run": quota_stop,
        "errors": errors[:20],
    }


def render_markdown(report: dict) -> str:
    labels = {
        "published": "✅ Publication produite",
        "empty_quota": "⚠️ Aucun article — quota Groq",
        "empty_editorial": "🟠 Aucun article — exigences éditoriales",
        "technical_failure": "❌ Échec technique",
        "dry_run": "ℹ️ Simulation",
        "empty_unknown": "⚪ Aucun résultat exploitable",
        "missing_log": "❌ Log introuvable",
    }
    lines = [
        "## Rapport automatique du pipeline",
        "",
        f"**Verdict : {labels.get(report.get('status'), report.get('status', 'inconnu'))}**",
        "",
        "| Indicateur | Valeur |",
        "|---|---:|",
        f"| Sujets envoyés à la génération | {report.get('attempts', 0)} |",
        f"| Articles admis par la grille vitrine | {report.get('accepted_showcase', 0)} |",
        f"| Articles annoncés en fin de run | {report.get('final_publications', 0)} |",
        f"| Rejets journalisés | {report.get('rejections', 0)} |",
        f"| Événements de quota | {report.get('quota_events', 0)} |",
    ]
    reasons = report.get("top_rejection_reasons") or []
    if reasons:
        lines += ["", "### Principaux motifs de rejet"]
        for item in reasons[:8]:
            lines.append(f"- {item['count']} × {item['reason']}")
    errors = report.get("errors") or []
    if errors:
        lines += ["", "### Erreurs techniques"]
        for error in errors[:8]:
            lines.append(f"- {error}")
    lines += [
        "",
        "_Les compteurs de publication doivent ensuite être confirmés par les fichiers "
        "réellement ajoutés sous `articles/` (`git diff --diff-filter=A`)._",
        "",
    ]
    return "\n".join(lines)


def summarize_file(path: Path) -> dict:
    if not path.exists():
        return {
            "status": "missing_log",
            "attempts": 0,
            "accepted_showcase": 0,
            "final_publications": 0,
            "rejections": 0,
            "top_rejection_reasons": [],
            "quota_events": 0,
            "quota_stopped_run": False,
            "errors": [f"Log introuvable : {path}"],
        }
    return summarize_text(path.read_text(encoding="utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    report = summarize_file(args.log)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    markdown = render_markdown(report)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
