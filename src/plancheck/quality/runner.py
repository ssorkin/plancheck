"""Run all data-quality checks and generate DATA_QUALITY.md."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from plancheck.paths import KNOWN_ISSUES_DIR, REPO_ROOT
from plancheck.quality.checks import ALL_CHECKS, Finding, check_manifest_hashes

REPORT_PATH = REPO_ROOT / "DATA_QUALITY.md"
SEVERITY_ORDER = {"anomaly": 0, "warning": 1, "info": 2}
SEVERITY_MARK = {"anomaly": "🔴", "warning": "🟡", "info": "ℹ️"}


def load_known_issues() -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in sorted(KNOWN_ISSUES_DIR.glob("*.yaml"))]


def run_checks(report_path: Path = REPORT_PATH, verify_hashes: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    print("  running check_manifest_hashes …")
    findings.extend(check_manifest_hashes(verify=verify_hashes))
    for check in ALL_CHECKS:
        print(f"  running {check.__name__} …")
        try:
            findings.extend(check())
        except Exception as exc:  # noqa: BLE001 — a broken check is itself a finding
            findings.append(Finding(check.__name__, "anomaly", None, f"check failed: {exc}"))
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.check, f.scope or ""))

    lines = [
        "# Data Quality Report",
        "",
        (
            f"Generated {datetime.now(UTC).date().isoformat()} by `pc check`. Problems in the "
            "source data are surfaced here and in `known_issues/`, never silently patched."
        ),
        "",
        "## Known issues (documented registry)",
        "",
    ]
    for issue in load_known_issues():
        years = ", ".join(str(y) for y in issue.get("years", []))
        lines += [
            f"### {issue['title']}",
            "",
            f"*{issue['kind']}, affects {issue['dataset']} {years}* — id `{issue['id']}`",
            "",
            issue["description"].strip(),
            "",
            f"**Handling:** {issue['handling'].strip()}",
            "",
        ]
    lines += ["## Check findings", ""]
    current = None
    for f in findings:
        if f.check != current:
            current = f.check
            lines += [f"### {f.check}", ""]
        scope = f" **{f.scope}**" if f.scope else ""
        lines.append(f"- {SEVERITY_MARK[f.severity]}{scope} {f.message}")
        for ex in f.details.get("examples", []):
            lines.append(f"  - {ex}")
    lines.append("")
    n_anom = sum(1 for f in findings if f.severity == "anomaly")
    n_warn = sum(1 for f in findings if f.severity == "warning")
    print(f"  {len(findings)} findings ({n_anom} anomalies, {n_warn} warnings)")
    report_path.write_text("\n".join(lines))
    print(f"  wrote {report_path.relative_to(REPO_ROOT)}")
    return findings
