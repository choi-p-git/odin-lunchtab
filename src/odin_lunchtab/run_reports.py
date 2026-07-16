from __future__ import annotations

import hashlib
from pathlib import Path

RECONCILIATION_RUN_SUMMARY_NAME = "Reconciliation Run Summary.md"
INITIAL_BALANCES_RUN_SUMMARY_NAME = "InitialBalances Run Summary.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_hashes(paths: list[Path]) -> list[dict[str, str]]:
    return [{"name": path.name, "sha256": sha256_file(path)} for path in paths if path.is_file()]


def write_reconciliation_run_summary(
    *,
    path: Path,
    profile_name: str,
    valid_odin_rows: int,
    malformed_rows: int,
    matched_by_id: int,
    matched_by_name: int,
    exceptions: int,
    manual_review_exceptions: int,
    lunchtab_rows: int,
    audit_control_status: str,
    audit_control_name: str,
    manual_review_name: str,
    exceptions_name: str,
    transfer_name: str,
) -> None:
    matched_total = matched_by_id + matched_by_name
    next_action = (
        f"Review `{manual_review_name}` before continuing to InitialBalances."
        if manual_review_exceptions
        else (
            f"Review `{exceptions_name}` for legacy or closed accounts, then continue to "
            "InitialBalances when operational review is complete."
            if exceptions
            else "Continue to InitialBalances transfer when operational review is complete."
        )
    )
    path.write_text(
        "\n".join(
            [
                "# Reconciliation Run Summary",
                "",
                f"- Matching profile: {profile_name}",
                f"- Audit-control status: {audit_control_status}",
                f"- Valid Odin rows: {valid_odin_rows}",
                f"- Malformed Odin rows: {malformed_rows}",
                f"- Matched rows: {matched_total}",
                f"- Matched by identifier/rule: {matched_by_id}",
                f"- Matched by name fallback: {matched_by_name}",
                f"- All exception rows: {exceptions}",
                f"- Manual-review exception rows: {manual_review_exceptions}",
                f"- LunchTab output rows: {lunchtab_rows}",
                "",
                "## Key artifacts",
                "",
                f"- Transfer CSV: `{transfer_name}`",
                f"- Audit-control summary: `{audit_control_name}`",
                f"- Manual-review exceptions: `{manual_review_name}`",
                f"- Complete exceptions: `{exceptions_name}`",
                "",
                "## Recommended next action",
                "",
                next_action,
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_initial_balances_run_summary(
    *,
    path: Path,
    blocked: bool,
    populated_balance_rows: int,
    matched_source_rows: int,
    updated_families: int,
    exceptions: int,
    source_total: str,
    applied_total: str,
    original_matched_total: str,
    final_matched_total: str,
    audit_control_status: str,
    audit_control_name: str,
    audit_name: str,
    exceptions_name: str,
    processed_name: str | None,
) -> None:
    run_status = "BLOCKED" if blocked else "READY"
    next_action = (
        f"Resolve `{exceptions_name}` and rerun InitialBalances before importing."
        if blocked
        else f"Import `{processed_name}` after final operational approval."
    )
    processed_line = (
        f"- Processed import: `{processed_name}`"
        if processed_name is not None
        else "- Processed import: not created because the run is blocked"
    )
    path.write_text(
        "\n".join(
            [
                "# InitialBalances Run Summary",
                "",
                f"- Run status: {run_status}",
                f"- Audit-control status: {audit_control_status}",
                f"- Populated transfer rows: {populated_balance_rows}",
                f"- Matched source rows: {matched_source_rows}",
                f"- Updated families: {updated_families}",
                f"- Exception rows: {exceptions}",
                f"- Source total: {source_total}",
                f"- Applied total: {applied_total}",
                f"- Original matched total: {original_matched_total}",
                f"- Final matched total: {final_matched_total}",
                "",
                "## Key artifacts",
                "",
                processed_line,
                f"- Transfer audit: `{audit_name}`",
                f"- Audit-control summary: `{audit_control_name}`",
                f"- Exceptions: `{exceptions_name}`",
                "",
                "## Recommended next action",
                "",
                next_action,
                "",
            ]
        ),
        encoding="utf-8",
    )
