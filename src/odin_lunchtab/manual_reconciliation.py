from __future__ import annotations

import csv
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from odin_lunchtab.managed import application_version, choose_run_dir
from odin_lunchtab.run_reports import artifact_hashes, sha256_file
from odin_lunchtab.workflow import read_csv, read_csv_with_metadata

DELTA_AUDIT_NAME = "Manual Reconciliation Delta Audit.csv"
DELTA_SUMMARY_NAME = "Manual Reconciliation Summary.md"
MANIFEST_NAME = "manual-reconciliation-manifest.json"
BALANCE_FIELD = "OdinBalanceAmount"
FAMILY_FIELD = "DefaultFamilyCode"
IDENTITY_FIELDS = {
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "ExternalId",
    "EmailAddress",
}
DELTA_HEADERS = [
    "ChangeType",
    "Severity",
    "RowNumber",
    "FieldName",
    "OriginalValue",
    "EditedValue",
    "Identifier",
    "Notes",
]


@dataclass(frozen=True)
class ManualReconciliationOutputPaths:
    delta_audit: Path
    summary: Path


@dataclass(frozen=True)
class ManualReconciliationSummary:
    original_rows: int
    edited_rows: int
    unchanged_automated_matches: int
    manual_resolutions: int
    changed_automated_balances: int
    cleared_automated_balances: int
    invalid_manual_amounts: int
    family_code_changes: int
    identity_field_changes: int
    other_field_changes: int
    status: str
    output_paths: ManualReconciliationOutputPaths


@dataclass(frozen=True)
class ManualReconciliationRunResult:
    run_dir: Path
    summary: ManualReconciliationSummary
    manifest_path: Path


def _decimal_or_none(value: str) -> Decimal | None:
    cleaned = value.replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _identifier(row: dict[str, str], row_number: int) -> str:
    for field in ("LoginBarcode", "ExternalId", "EmailAddress", "DefaultFamilyCode"):
        value = (row.get(field) or "").strip()
        if value:
            return f"{field}={value}"
    return f"row={row_number}"


def _delta_row(
    *,
    change_type: str,
    severity: str,
    row_number: int,
    field_name: str,
    original_value: str,
    edited_value: str,
    identifier: str,
    notes: str,
) -> dict[str, str]:
    return {
        "ChangeType": change_type,
        "Severity": severity,
        "RowNumber": str(row_number),
        "FieldName": field_name,
        "OriginalValue": original_value,
        "EditedValue": edited_value,
        "Identifier": identifier,
        "Notes": notes,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=DELTA_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(path: Path, summary: ManualReconciliationSummary) -> None:
    next_action = (
        "Review high-risk changes before using the edited transfer for InitialBalances."
        if summary.status != "PASS"
        else "The edited transfer is ready for InitialBalances preflight."
    )
    path.write_text(
        "\n".join(
            [
                "# Manual Reconciliation Summary",
                "",
                f"- Status: {summary.status}",
                f"- Original transfer rows: {summary.original_rows}",
                f"- Edited transfer rows: {summary.edited_rows}",
                f"- Unchanged automated matches: {summary.unchanged_automated_matches}",
                f"- Manual resolutions: {summary.manual_resolutions}",
                f"- Changed automated balances: {summary.changed_automated_balances}",
                f"- Cleared automated balances: {summary.cleared_automated_balances}",
                f"- Invalid manual amounts: {summary.invalid_manual_amounts}",
                f"- Family-code changes: {summary.family_code_changes}",
                f"- Identity-field changes: {summary.identity_field_changes}",
                f"- Other field changes: {summary.other_field_changes}",
                "",
                "## Recommended next action",
                "",
                next_action,
                "",
            ]
        ),
        encoding="utf-8",
    )


def audit_manual_reconciliation(
    *,
    original_transfer_path: Path,
    edited_transfer_path: Path,
    output_dir: Path,
) -> ManualReconciliationSummary:
    original_headers, original_rows = read_csv(original_transfer_path)
    edited_headers, edited_rows = read_csv(edited_transfer_path)
    if original_headers != edited_headers:
        raise ValueError("Edited transfer headers must match the original transfer headers.")
    if BALANCE_FIELD not in original_headers:
        raise ValueError(f"Transfer CSV is missing required column: {BALANCE_FIELD}")
    if len(original_rows) != len(edited_rows):
        raise ValueError("Edited transfer row count must match the original transfer row count.")

    delta_rows: list[dict[str, str]] = []
    unchanged_automated_matches = 0
    manual_resolutions = 0
    changed_automated_balances = 0
    cleared_automated_balances = 0
    invalid_manual_amounts = 0
    family_code_changes = 0
    identity_field_changes = 0
    other_field_changes = 0

    for index, (original, edited) in enumerate(zip(original_rows, edited_rows, strict=True)):
        row_number = index + 2
        identifier = _identifier(edited, row_number)
        original_balance = (original.get(BALANCE_FIELD) or "").strip()
        edited_balance = (edited.get(BALANCE_FIELD) or "").strip()
        edited_amount = _decimal_or_none(edited_balance)

        if edited_balance and edited_amount is None:
            invalid_manual_amounts += 1
            delta_rows.append(
                _delta_row(
                    change_type="invalid manual amount",
                    severity="BLOCKING",
                    row_number=row_number,
                    field_name=BALANCE_FIELD,
                    original_value=original_balance,
                    edited_value=edited_balance,
                    identifier=identifier,
                    notes="Edited OdinBalanceAmount must be a valid finite decimal.",
                )
            )
        elif not original_balance and edited_balance:
            manual_resolutions += 1
            delta_rows.append(
                _delta_row(
                    change_type="manual resolution",
                    severity="REVIEW",
                    row_number=row_number,
                    field_name=BALANCE_FIELD,
                    original_value=original_balance,
                    edited_value=edited_balance,
                    identifier=identifier,
                    notes="Previously unresolved row now has a manually supplied balance.",
                )
            )
        elif original_balance and not edited_balance:
            cleared_automated_balances += 1
            delta_rows.append(
                _delta_row(
                    change_type="cleared automated balance",
                    severity="HIGH",
                    row_number=row_number,
                    field_name=BALANCE_FIELD,
                    original_value=original_balance,
                    edited_value=edited_balance,
                    identifier=identifier,
                    notes="Automated matched balance was removed.",
                )
            )
        elif original_balance and edited_balance and original_balance != edited_balance:
            changed_automated_balances += 1
            delta_rows.append(
                _delta_row(
                    change_type="changed automated balance",
                    severity="HIGH",
                    row_number=row_number,
                    field_name=BALANCE_FIELD,
                    original_value=original_balance,
                    edited_value=edited_balance,
                    identifier=identifier,
                    notes="Automated matched balance was changed.",
                )
            )
        elif original_balance and edited_balance:
            unchanged_automated_matches += 1

        for field in original_headers:
            if field == BALANCE_FIELD:
                continue
            original_value = original.get(field, "")
            edited_value = edited.get(field, "")
            if original_value == edited_value:
                continue
            if field == FAMILY_FIELD:
                family_code_changes += 1
                change_type = "family code changed"
                severity = "HIGH"
                notes = "DefaultFamilyCode changed; verify destination family before import."
            elif field in IDENTITY_FIELDS:
                identity_field_changes += 1
                change_type = "identity field changed"
                severity = "HIGH"
                notes = "LunchTab identity field changed; verify this was intentional."
            else:
                other_field_changes += 1
                change_type = "non-balance field changed"
                severity = "REVIEW"
                notes = "Non-balance field changed in edited transfer."
            delta_rows.append(
                _delta_row(
                    change_type=change_type,
                    severity=severity,
                    row_number=row_number,
                    field_name=field,
                    original_value=original_value,
                    edited_value=edited_value,
                    identifier=identifier,
                    notes=notes,
                )
            )

    status = (
        "BLOCKED"
        if invalid_manual_amounts
        else "REVIEW"
        if (
            changed_automated_balances
            or cleared_automated_balances
            or family_code_changes
            or identity_field_changes
            or other_field_changes
        )
        else "PASS"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = ManualReconciliationOutputPaths(
        delta_audit=output_dir / DELTA_AUDIT_NAME,
        summary=output_dir / DELTA_SUMMARY_NAME,
    )
    summary = ManualReconciliationSummary(
        original_rows=len(original_rows),
        edited_rows=len(edited_rows),
        unchanged_automated_matches=unchanged_automated_matches,
        manual_resolutions=manual_resolutions,
        changed_automated_balances=changed_automated_balances,
        cleared_automated_balances=cleared_automated_balances,
        invalid_manual_amounts=invalid_manual_amounts,
        family_code_changes=family_code_changes,
        identity_field_changes=identity_field_changes,
        other_field_changes=other_field_changes,
        status=status,
        output_paths=paths,
    )
    _write_csv(paths.delta_audit, delta_rows)
    _write_summary(paths.summary, summary)
    return summary


def _manifest(
    *,
    started_at: datetime,
    completed_at: datetime,
    original_transfer_path: Path,
    edited_transfer_path: Path,
    summary: ManualReconciliationSummary,
) -> dict[str, object]:
    counts = asdict(summary)
    counts.pop("output_paths")
    _, _, original_encoding = read_csv_with_metadata(original_transfer_path)
    _, _, edited_encoding = read_csv_with_metadata(edited_transfer_path)
    return {
        "application": "Odin to Lunchtab Balance Transfer",
        "version": application_version(),
        "workflow": "Manual Reconciliation Review",
        "started_at": started_at.astimezone().isoformat(),
        "completed_at": completed_at.astimezone().isoformat(),
        "inputs": {
            "original_transfer": {
                "name": original_transfer_path.name,
                "encoding": original_encoding.encoding,
                "used_fallback": original_encoding.used_fallback,
            },
            "edited_transfer": {
                "name": edited_transfer_path.name,
                "encoding": edited_encoding.encoding,
                "used_fallback": edited_encoding.used_fallback,
            },
        },
        "input_hashes": {
            "original_transfer": {
                "name": original_transfer_path.name,
                "sha256": sha256_file(original_transfer_path),
            },
            "edited_transfer": {
                "name": edited_transfer_path.name,
                "sha256": sha256_file(edited_transfer_path),
            },
        },
        "summary": counts,
        "review_status": summary.status,
        "generated_files": [path.name for path in asdict(summary.output_paths).values()],
        "generated_artifact_hashes": artifact_hashes(
            [path for path in asdict(summary.output_paths).values()]
        ),
    }


def run_manual_reconciliation_workflow(
    *,
    original_transfer_path: Path,
    edited_transfer_path: Path,
    output_root: Path,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> ManualReconciliationRunResult:
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = now()
    run_dir = choose_run_dir(output_root, started_at)
    staging_dir = output_root / f".staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()
    try:
        summary = audit_manual_reconciliation(
            original_transfer_path=original_transfer_path,
            edited_transfer_path=edited_transfer_path,
            output_dir=staging_dir,
        )
        completed_at = now()
        manifest_path = staging_dir / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(
                _manifest(
                    started_at=started_at,
                    completed_at=completed_at,
                    original_transfer_path=original_transfer_path,
                    edited_transfer_path=edited_transfer_path,
                    summary=summary,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        staging_dir.rename(run_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    output_paths = ManualReconciliationOutputPaths(
        delta_audit=run_dir / summary.output_paths.delta_audit.name,
        summary=run_dir / summary.output_paths.summary.name,
    )
    return ManualReconciliationRunResult(
        run_dir=run_dir,
        summary=replace(summary, output_paths=output_paths),
        manifest_path=run_dir / MANIFEST_NAME,
    )
