from __future__ import annotations

import csv
import json
import shutil
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from odin_lunchtab.audit_control import (
    INITIAL_BALANCES_AUDIT_CONTROL_NAME,
    write_initial_balances_audit_control,
)
from odin_lunchtab.managed import application_version, choose_run_dir
from odin_lunchtab.run_reports import (
    INITIAL_BALANCES_RUN_SUMMARY_NAME,
    artifact_hashes,
    sha256_file,
    write_initial_balances_run_summary,
)
from odin_lunchtab.workflow import read_csv, read_csv_with_metadata

TRANSFER_HEADERS = {"DefaultFamilyCode", "OdinBalanceAmount"}
INITIAL_BALANCE_HEADERS = ["FamilyName", "FamilyCode", "Amount"]
AUDIT_HEADERS = [
    "FamilyCode",
    "SourceRowCount",
    "OriginalAmount",
    "AggregatedOdinAmount",
    "FinalAmount",
    "Status",
]
EXCEPTION_HEADERS = ["Reason", "Source", "RowNumber", "FamilyCode", "Value"]
AUDIT_OUTPUT_NAME = "InitialBalances Transfer Audit.csv"
EXCEPTIONS_OUTPUT_NAME = "InitialBalances Transfer Exceptions.csv"
MANIFEST_NAME = "initial-balances-manifest.json"


@dataclass(frozen=True)
class InitialBalancesInspection:
    transfer_path: Path
    initial_balances_path: Path
    transfer_rows: int
    populated_balance_rows: int
    initial_balance_rows: int


@dataclass(frozen=True)
class InitialBalancesPreflight:
    transfer_rows: int
    populated_balance_rows: int
    target_rows: int
    matched_source_rows: int
    updated_families: int
    exceptions: int
    source_total: str
    applied_total: str
    blocked_total: str
    original_matched_total: str
    final_matched_total: str
    blocked: bool
    exception_reasons: dict[str, int]


@dataclass(frozen=True)
class InitialBalancesOutputPaths:
    processed: Path | None
    audit: Path
    exceptions: Path
    audit_control: Path | None = None
    run_summary: Path | None = None


@dataclass(frozen=True)
class InitialBalancesSummary:
    transfer_rows: int
    populated_balance_rows: int
    target_rows: int
    matched_source_rows: int
    updated_families: int
    exceptions: int
    source_total: str
    original_matched_total: str
    final_matched_total: str
    applied_total: str
    blocked: bool
    output_paths: InitialBalancesOutputPaths
    audit_control_status: str = "PASS"


@dataclass(frozen=True)
class InitialBalancesRunResult:
    run_dir: Path
    summary: InitialBalancesSummary
    manifest_path: Path


@dataclass(frozen=True)
class _InitialBalancesAnalysis:
    inspection: InitialBalancesInspection
    transfer_rows: list[dict[str, str]]
    target_headers: list[str]
    output_rows: list[dict[str, str]]
    audit_rows: list[dict[str, str]]
    exceptions: list[dict[str, str]]
    source_total: Decimal
    original_total: Decimal
    final_total: Decimal
    applied_total: Decimal
    preflight: InitialBalancesPreflight


def _decimal(value: str, *, blank_as_zero: bool = False) -> Decimal:
    cleaned = value.replace(",", "").replace("$", "").strip()
    if blank_as_zero and not cleaned:
        return Decimal("0")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError("invalid monetary value") from error
    if not amount.is_finite():
        raise ValueError("invalid monetary value")
    return amount


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _validate_file(path: Path, description: str) -> None:
    if path.suffix.casefold() != ".csv":
        raise ValueError(f"The {description} must be a .csv file.")
    if not path.is_file():
        raise FileNotFoundError(f"{description.capitalize()} does not exist: {path}")


def inspect_initial_balances_inputs(
    transfer_path: Path,
    initial_balances_path: Path,
) -> InitialBalancesInspection:
    _validate_file(transfer_path, "reconciled transfer")
    _validate_file(initial_balances_path, "InitialBalances export")
    transfer_headers, transfer_rows = read_csv(transfer_path)
    missing = sorted(TRANSFER_HEADERS - set(transfer_headers))
    if missing:
        raise ValueError(f"Reconciled transfer is missing required columns: {', '.join(missing)}")
    target_headers, target_rows = read_csv(initial_balances_path)
    if target_headers != INITIAL_BALANCE_HEADERS:
        raise ValueError(
            "InitialBalances export must contain exactly these columns in order: "
            "FamilyName, FamilyCode, Amount"
        )
    return InitialBalancesInspection(
        transfer_path=transfer_path,
        initial_balances_path=initial_balances_path,
        transfer_rows=len(transfer_rows),
        populated_balance_rows=sum(
            bool((row.get("OdinBalanceAmount") or "").strip()) for row in transfer_rows
        ),
        initial_balance_rows=len(target_rows),
    )


def _exception(
    reason: str,
    source: str,
    row_number: int,
    family_code: str,
    value: str,
) -> dict[str, str]:
    return {
        "Reason": reason,
        "Source": source,
        "RowNumber": str(row_number),
        "FamilyCode": family_code,
        "Value": value,
    }


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _audit_generated_file(
    path: Path,
    expected_rows: list[dict[str, str]],
    expected_headers: list[str],
) -> None:
    headers, rows = read_csv(path)
    if headers != expected_headers:
        raise RuntimeError("Generated InitialBalances headers failed the integrity audit.")
    if rows != expected_rows:
        raise RuntimeError("Generated InitialBalances rows failed the integrity audit.")


def _analyze_initial_balances(
    transfer_path: Path,
    initial_balances_path: Path,
) -> _InitialBalancesAnalysis:
    inspection = inspect_initial_balances_inputs(transfer_path, initial_balances_path)
    _, transfer_rows = read_csv(transfer_path)
    target_headers, target_rows = read_csv(initial_balances_path)
    exceptions: list[dict[str, str]] = []
    amounts_by_code: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    source_counts: Counter[str] = Counter()
    source_total = Decimal("0")
    blank_code_total = Decimal("0")

    for row_number, row in enumerate(transfer_rows, start=2):
        raw_amount = row.get("OdinBalanceAmount") or ""
        if not raw_amount.strip():
            continue
        code = (row.get("DefaultFamilyCode") or "").strip()
        if not code:
            try:
                amount = _decimal(raw_amount)
            except ValueError:
                exceptions.append(
                    _exception(
                        "invalid OdinBalanceAmount",
                        "reconciled transfer",
                        row_number,
                        "",
                        raw_amount,
                    )
                )
                continue
            blank_code_total += amount
            exceptions.append(
                _exception(
                    "populated balance has blank DefaultFamilyCode",
                    "reconciled transfer",
                    row_number,
                    "",
                    raw_amount,
                )
            )
            continue
        try:
            amount = _decimal(raw_amount)
        except ValueError:
            exceptions.append(
                _exception(
                    "invalid OdinBalanceAmount",
                    "reconciled transfer",
                    row_number,
                    code,
                    raw_amount,
                )
            )
            continue
        amounts_by_code[code] += amount
        source_counts[code] += 1
        source_total += amount

    target_indexes: dict[str, list[int]] = defaultdict(list)
    parsed_target_amounts: dict[int, Decimal] = {}
    for index, row in enumerate(target_rows):
        row_number = index + 2
        code = (row.get("FamilyCode") or "").strip()
        if code:
            target_indexes[code].append(index)
        if code in amounts_by_code:
            try:
                parsed_target_amounts[index] = _decimal(row.get("Amount") or "", blank_as_zero=True)
            except ValueError:
                exceptions.append(
                    _exception(
                        "invalid target Amount",
                        "InitialBalances",
                        row_number,
                        code,
                        row.get("Amount") or "",
                    )
                )

    for code in amounts_by_code:
        indexes = target_indexes.get(code, [])
        if not indexes:
            exceptions.append(
                _exception(
                    "DefaultFamilyCode not found in InitialBalances",
                    "reconciled transfer",
                    0,
                    code,
                    _decimal_text(amounts_by_code[code]),
                )
            )
        elif len(indexes) > 1:
            exceptions.append(
                _exception(
                    "duplicate FamilyCode in InitialBalances",
                    "InitialBalances",
                    0,
                    code,
                    str(len(indexes)),
                )
            )

    output_rows = [dict(row) for row in target_rows]
    audit_rows: list[dict[str, str]] = []
    original_total = Decimal("0")
    final_total = Decimal("0")
    applied_total = Decimal("0")
    blocked_total = blank_code_total
    updated_families = 0
    blocked_codes = {row["FamilyCode"] for row in exceptions if row["FamilyCode"]}

    for code, amount in amounts_by_code.items():
        indexes = target_indexes.get(code, [])
        if len(indexes) == 1 and code not in blocked_codes:
            index = indexes[0]
            original = parsed_target_amounts[index]
            final = original + amount
            output_rows[index]["Amount"] = _decimal_text(final)
            original_total += original
            final_total += final
            applied_total += amount
            updated_families += 1
            status = "updated"
        else:
            original = Decimal("0")
            final = Decimal("0")
            status = "blocked"
            blocked_total += amount
        audit_rows.append(
            {
                "FamilyCode": code,
                "SourceRowCount": str(source_counts[code]),
                "OriginalAmount": _decimal_text(original),
                "AggregatedOdinAmount": _decimal_text(amount),
                "FinalAmount": _decimal_text(final),
                "Status": status,
            }
        )

    blocked = bool(exceptions)
    matched_source_rows = sum(
        source_counts[code]
        for code in amounts_by_code
        if len(target_indexes.get(code, [])) == 1 and code not in blocked_codes
    )
    preflight = InitialBalancesPreflight(
        transfer_rows=inspection.transfer_rows,
        populated_balance_rows=inspection.populated_balance_rows,
        target_rows=inspection.initial_balance_rows,
        matched_source_rows=matched_source_rows,
        updated_families=updated_families,
        exceptions=len(exceptions),
        source_total=_decimal_text(source_total + blank_code_total),
        applied_total=_decimal_text(applied_total),
        blocked_total=_decimal_text(blocked_total),
        original_matched_total=_decimal_text(original_total),
        final_matched_total=_decimal_text(final_total),
        blocked=blocked,
        exception_reasons=dict(sorted(Counter(row["Reason"] for row in exceptions).items())),
    )
    return _InitialBalancesAnalysis(
        inspection=inspection,
        transfer_rows=transfer_rows,
        target_headers=target_headers,
        output_rows=output_rows,
        audit_rows=audit_rows,
        exceptions=exceptions,
        source_total=source_total,
        original_total=original_total,
        final_total=final_total,
        applied_total=applied_total,
        preflight=preflight,
    )


def preflight_initial_balances_transfer(
    transfer_path: Path,
    initial_balances_path: Path,
) -> InitialBalancesPreflight:
    return _analyze_initial_balances(transfer_path, initial_balances_path).preflight


def process_initial_balances(
    *,
    transfer_path: Path,
    initial_balances_path: Path,
    output_dir: Path,
) -> InitialBalancesSummary:
    analysis = _analyze_initial_balances(transfer_path, initial_balances_path)
    inspection = analysis.inspection
    target_headers = analysis.target_headers
    output_rows = analysis.output_rows
    audit_rows = analysis.audit_rows
    exceptions = analysis.exceptions
    preflight = analysis.preflight
    source_total = analysis.source_total
    applied_total = analysis.applied_total
    original_total = analysis.original_total
    final_total = analysis.final_total
    blocked = preflight.blocked
    updated_families = preflight.updated_families
    matched_source_rows = preflight.matched_source_rows
    if not blocked:
        if applied_total != source_total or final_total - original_total != source_total:
            raise RuntimeError("InitialBalances control totals failed the integrity audit.")

    output_dir.mkdir(parents=True, exist_ok=True)
    processed_path = output_dir / f"Processed - {initial_balances_path.name}"
    audit_path = output_dir / AUDIT_OUTPUT_NAME
    exceptions_path = output_dir / EXCEPTIONS_OUTPUT_NAME
    audit_control_path = output_dir / INITIAL_BALANCES_AUDIT_CONTROL_NAME
    run_summary_path = output_dir / INITIAL_BALANCES_RUN_SUMMARY_NAME
    _write_csv(audit_path, AUDIT_HEADERS, audit_rows)
    _write_csv(exceptions_path, EXCEPTION_HEADERS, exceptions)
    audit_control_status = write_initial_balances_audit_control(
        path=audit_control_path,
        transfer_rows=analysis.transfer_rows,
        family_audit_rows=audit_rows,
        exceptions=exceptions,
        transfer_name=transfer_path.name,
        family_audit_name=audit_path.name,
        exceptions_name=exceptions_path.name,
    )
    if audit_control_status != "PASS":
        raise RuntimeError("InitialBalances audit-control totals failed the integrity audit.")
    if blocked:
        processed: Path | None = None
    else:
        _write_csv(processed_path, target_headers, output_rows)
        _audit_generated_file(processed_path, output_rows, target_headers)
        processed = processed_path
    write_initial_balances_run_summary(
        path=run_summary_path,
        blocked=blocked,
        populated_balance_rows=inspection.populated_balance_rows,
        matched_source_rows=matched_source_rows,
        updated_families=updated_families,
        exceptions=len(exceptions),
        source_total=_decimal_text(source_total),
        applied_total=_decimal_text(applied_total),
        original_matched_total=_decimal_text(original_total),
        final_matched_total=_decimal_text(final_total),
        audit_control_status=audit_control_status,
        audit_control_name=audit_control_path.name,
        audit_name=audit_path.name,
        exceptions_name=exceptions_path.name,
        processed_name=processed.name if processed is not None else None,
    )

    return InitialBalancesSummary(
        transfer_rows=inspection.transfer_rows,
        populated_balance_rows=inspection.populated_balance_rows,
        target_rows=inspection.initial_balance_rows,
        matched_source_rows=matched_source_rows,
        updated_families=updated_families,
        exceptions=len(exceptions),
        source_total=_decimal_text(source_total),
        original_matched_total=_decimal_text(original_total),
        final_matched_total=_decimal_text(final_total),
        applied_total=_decimal_text(applied_total),
        blocked=blocked,
        output_paths=InitialBalancesOutputPaths(
            processed,
            audit_path,
            exceptions_path,
            audit_control_path,
            run_summary_path,
        ),
        audit_control_status=audit_control_status,
    )


def _manifest(
    *,
    started_at: datetime,
    completed_at: datetime,
    transfer_path: Path,
    initial_balances_path: Path,
    summary: InitialBalancesSummary,
) -> dict[str, object]:
    counts = asdict(summary)
    counts.pop("output_paths")
    _, _, transfer_encoding = read_csv_with_metadata(transfer_path)
    _, _, initial_encoding = read_csv_with_metadata(initial_balances_path)
    return {
        "application": "Odin to Lunchtab Balance Transfer",
        "version": application_version(),
        "workflow": "InitialBalances Transfer",
        "started_at": started_at.astimezone().isoformat(),
        "completed_at": completed_at.astimezone().isoformat(),
        "inputs": {
            "reconciled_transfer": {
                "name": transfer_path.name,
                "encoding": transfer_encoding.encoding,
                "used_fallback": transfer_encoding.used_fallback,
            },
            "initial_balances": {
                "name": initial_balances_path.name,
                "encoding": initial_encoding.encoding,
                "used_fallback": initial_encoding.used_fallback,
            },
        },
        "input_hashes": {
            "reconciled_transfer": {
                "name": transfer_path.name,
                "sha256": sha256_file(transfer_path),
            },
            "initial_balances": {
                "name": initial_balances_path.name,
                "sha256": sha256_file(initial_balances_path),
            },
        },
        "summary": counts,
        "audit_control": {
            "status": summary.audit_control_status,
            "report": (
                summary.output_paths.audit_control.name
                if summary.output_paths.audit_control is not None
                else None
            ),
        },
        "generated_files": [
            path.name for path in asdict(summary.output_paths).values() if path is not None
        ],
        "generated_artifact_hashes": artifact_hashes(
            [path for path in asdict(summary.output_paths).values() if path is not None]
        ),
    }


def run_initial_balances_workflow(
    *,
    transfer_path: Path,
    initial_balances_path: Path,
    output_root: Path,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> InitialBalancesRunResult:
    inspect_initial_balances_inputs(transfer_path, initial_balances_path)
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = now()
    run_dir = choose_run_dir(output_root, started_at)
    staging_dir = output_root / f".staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()
    try:
        summary = process_initial_balances(
            transfer_path=transfer_path,
            initial_balances_path=initial_balances_path,
            output_dir=staging_dir,
        )
        completed_at = now()
        manifest_path = staging_dir / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(
                _manifest(
                    started_at=started_at,
                    completed_at=completed_at,
                    transfer_path=transfer_path,
                    initial_balances_path=initial_balances_path,
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

    output_paths = InitialBalancesOutputPaths(
        processed=(
            run_dir / summary.output_paths.processed.name
            if summary.output_paths.processed is not None
            else None
        ),
        audit=run_dir / summary.output_paths.audit.name,
        exceptions=run_dir / summary.output_paths.exceptions.name,
        audit_control=(
            run_dir / summary.output_paths.audit_control.name
            if summary.output_paths.audit_control is not None
            else None
        ),
        run_summary=(
            run_dir / summary.output_paths.run_summary.name
            if summary.output_paths.run_summary is not None
            else None
        ),
    )
    rebased = replace(summary, output_paths=output_paths)
    return InitialBalancesRunResult(
        run_dir=run_dir,
        summary=rebased,
        manifest_path=run_dir / MANIFEST_NAME,
    )
