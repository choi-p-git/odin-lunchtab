from __future__ import annotations

import csv
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

RECONCILIATION_AUDIT_CONTROL_NAME = "Reconciliation Audit Control Summary.csv"
INITIAL_BALANCES_AUDIT_CONTROL_NAME = "InitialBalances Audit Control Summary.csv"

AUDIT_CONTROL_HEADERS = [
    "Workflow",
    "Category",
    "Subcategory",
    "RowCount",
    "AmountTotal",
    "EvidenceArtifact",
    "ControlStatus",
    "Notes",
]


def _decimal(value: str) -> Decimal:
    cleaned = value.replace(",", "").replace("$", "").strip()
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, AttributeError) as error:
        raise ValueError("invalid monetary value") from error
    if not amount.is_finite():
        raise ValueError("invalid monetary value")
    return amount


def _decimal_or_none(value: str) -> Decimal | None:
    try:
        return _decimal(value)
    except ValueError:
        return None


def _decimal_text(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=AUDIT_CONTROL_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _row(
    *,
    workflow: str,
    category: str,
    subcategory: str,
    count: int,
    amount: Decimal | None,
    artifact: str,
    status: str,
    notes: str = "",
) -> dict[str, str]:
    return {
        "Workflow": workflow,
        "Category": category,
        "Subcategory": subcategory,
        "RowCount": str(count),
        "AmountTotal": _decimal_text(amount),
        "EvidenceArtifact": artifact,
        "ControlStatus": status,
        "Notes": notes,
    }


def write_reconciliation_audit_control(
    *,
    path: Path,
    records: list[object],
    malformed: list[object],
    decisions: list[object],
    exceptions: list[dict[str, str]],
    processed_odin_name: str,
    match_audit_name: str,
    exceptions_name: str,
) -> str:
    workflow = "Odin to Lunchtab Reconciliation"
    valid_source_total = sum((_decimal(record.balance) for record in records), Decimal("0"))
    matched_total = sum((_decimal(decision.record.balance) for decision in decisions), Decimal("0"))

    rows: list[dict[str, str]] = [
        _row(
            workflow=workflow,
            category="Source",
            subcategory="Valid Odin source rows",
            count=len(records),
            amount=valid_source_total,
            artifact=processed_odin_name,
            status="PASS",
            notes="Valid extracted Odin rows included in dollar reconciliation.",
        )
    ]

    matches_by_subcategory: dict[str, list[object]] = defaultdict(list)
    for decision in decisions:
        matches_by_subcategory[f"{decision.method}: {decision.rule_name}"].append(decision)
    for subcategory, grouped in sorted(matches_by_subcategory.items()):
        rows.append(
            _row(
                workflow=workflow,
                category="Matched",
                subcategory=subcategory,
                count=len(grouped),
                amount=sum(
                    (_decimal(decision.record.balance) for decision in grouped),
                    Decimal("0"),
                ),
                artifact=match_audit_name,
                status="PASS",
            )
        )

    malformed_reason_counts = Counter(item.reason for item in malformed)
    malformed_amounts: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    malformed_parseable_counts: Counter[str] = Counter()
    for item in malformed:
        padded = (*item.values, *([""] * 6))
        amount = _decimal_or_none(padded[4])
        if amount is not None:
            malformed_amounts[item.reason] += amount
            malformed_parseable_counts[item.reason] += 1
    for reason, count in sorted(malformed_reason_counts.items()):
        rows.append(
            _row(
                workflow=workflow,
                category="Excluded",
                subcategory=f"Malformed Odin row: {reason}",
                count=count,
                amount=malformed_amounts.get(reason),
                artifact=exceptions_name,
                status="PASS",
                notes=(
                    "Malformed rows are excluded from the valid-source dollar control; "
                    f"{malformed_parseable_counts[reason]} row(s) had parseable balances."
                ),
            )
        )

    valid_exceptions = exceptions[len(malformed) :]
    exception_counts = Counter(row["Reason"] for row in valid_exceptions)
    exception_amounts: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for exception in valid_exceptions:
        amount = _decimal_or_none(exception.get("Balance", ""))
        if amount is not None:
            exception_amounts[exception["Reason"]] += amount
    for reason, count in sorted(exception_counts.items()):
        rows.append(
            _row(
                workflow=workflow,
                category="Exception",
                subcategory=reason,
                count=count,
                amount=exception_amounts.get(reason),
                artifact=exceptions_name,
                status="PASS",
            )
        )

    exception_total = sum(exception_amounts.values(), Decimal("0"))
    control_status = "PASS" if valid_source_total == matched_total + exception_total else "FAIL"
    rows.append(
        _row(
            workflow=workflow,
            category="Control Total",
            subcategory="Valid source = matched + valid exceptions",
            count=len(records),
            amount=matched_total + exception_total,
            artifact=f"{processed_odin_name} | {match_audit_name} | {exceptions_name}",
            status=control_status,
            notes=f"Valid source total: {_decimal_text(valid_source_total)}",
        )
    )
    _write_csv(path, rows)
    return control_status


def write_initial_balances_audit_control(
    *,
    path: Path,
    transfer_rows: list[dict[str, str]],
    family_audit_rows: list[dict[str, str]],
    exceptions: list[dict[str, str]],
    transfer_name: str,
    family_audit_name: str,
    exceptions_name: str,
) -> str:
    workflow = "InitialBalances Transfer"
    rows: list[dict[str, str]] = []

    valid_source_total = Decimal("0")
    valid_source_rows = 0
    invalid_source_rows = 0
    blank_code_total = Decimal("0")
    blank_code_rows = 0
    for transfer_row in transfer_rows:
        raw_amount = transfer_row.get("OdinBalanceAmount") or ""
        if not raw_amount.strip():
            continue
        amount = _decimal_or_none(raw_amount)
        if amount is None:
            invalid_source_rows += 1
            continue
        valid_source_rows += 1
        valid_source_total += amount
        if not (transfer_row.get("DefaultFamilyCode") or "").strip():
            blank_code_rows += 1
            blank_code_total += amount

    rows.append(
        _row(
            workflow=workflow,
            category="Source",
            subcategory="Valid populated transfer rows",
            count=valid_source_rows,
            amount=valid_source_total,
            artifact=transfer_name,
            status="PASS",
            notes="Rows with parseable OdinBalanceAmount values.",
        )
    )
    if invalid_source_rows:
        rows.append(
            _row(
                workflow=workflow,
                category="Excluded",
                subcategory="Invalid OdinBalanceAmount",
                count=invalid_source_rows,
                amount=None,
                artifact=exceptions_name,
                status="PASS",
                notes="Invalid amounts are counted but excluded from dollar controls.",
            )
        )

    applied_total = Decimal("0")
    applied_count = 0
    blocked_total = Decimal("0")
    blocked_count = 0
    original_total = Decimal("0")
    final_total = Decimal("0")
    for audit_row in family_audit_rows:
        amount = _decimal(audit_row["AggregatedOdinAmount"])
        source_count = int(audit_row["SourceRowCount"])
        if audit_row["Status"] == "updated":
            applied_total += amount
            applied_count += source_count
            original_total += _decimal(audit_row["OriginalAmount"])
            final_total += _decimal(audit_row["FinalAmount"])
        else:
            blocked_total += amount
            blocked_count += source_count

    rows.append(
        _row(
            workflow=workflow,
            category="Applied",
            subcategory="Updated InitialBalances families",
            count=applied_count,
            amount=applied_total,
            artifact=family_audit_name,
            status="PASS",
        )
    )

    reasons_by_code: dict[str, set[str]] = defaultdict(set)
    reason_counts = Counter(exception["Reason"] for exception in exceptions)
    reason_amounts: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for exception in exceptions:
        code = exception["FamilyCode"]
        reason = exception["Reason"]
        if code:
            reasons_by_code[code].add(reason)
        if exception["Source"] == "reconciled transfer":
            amount = _decimal_or_none(exception.get("Value", ""))
            if amount is not None:
                reason_amounts[reason] += amount

    for reason, count in sorted(reason_counts.items()):
        rows.append(
            _row(
                workflow=workflow,
                category="Exception Reason",
                subcategory=reason,
                count=count,
                amount=reason_amounts.get(reason),
                artifact=exceptions_name,
                status="PASS",
                notes="Reason counts are informational; blocked balance rows avoid double-counting.",
            )
        )

    if blank_code_rows:
        rows.append(
            _row(
                workflow=workflow,
                category="Blocked Balance",
                subcategory="populated balance has blank DefaultFamilyCode",
                count=blank_code_rows,
                amount=blank_code_total,
                artifact=exceptions_name,
                status="PASS",
            )
        )
    for audit_row in family_audit_rows:
        if audit_row["Status"] != "blocked":
            continue
        subcategory = " | ".join(sorted(reasons_by_code[audit_row["FamilyCode"]])) or "blocked"
        rows.append(
            _row(
                workflow=workflow,
                category="Blocked Balance",
                subcategory=subcategory,
                count=int(audit_row["SourceRowCount"]),
                amount=_decimal(audit_row["AggregatedOdinAmount"]),
                artifact=family_audit_name,
                status="PASS",
                notes="One row per blocked family code to avoid duplicate dollar counting.",
            )
        )

    total_blocked = blocked_total + blank_code_total
    source_control_status = (
        "PASS" if valid_source_total == applied_total + total_blocked else "FAIL"
    )
    rows.append(
        _row(
            workflow=workflow,
            category="Control Total",
            subcategory="Valid source = applied + blocked valid balances",
            count=valid_source_rows,
            amount=applied_total + total_blocked,
            artifact=f"{transfer_name} | {family_audit_name} | {exceptions_name}",
            status=source_control_status,
            notes=f"Valid source total: {_decimal_text(valid_source_total)}",
        )
    )

    final_control_status = "PASS" if final_total - original_total == applied_total else "FAIL"
    rows.append(
        _row(
            workflow=workflow,
            category="Control Total",
            subcategory="Final matched total - original matched total = applied total",
            count=applied_count,
            amount=final_total - original_total,
            artifact=family_audit_name,
            status=final_control_status,
            notes=f"Applied total: {_decimal_text(applied_total)}",
        )
    )

    control_status = "PASS" if source_control_status == final_control_status == "PASS" else "FAIL"
    _write_csv(path, rows)
    return control_status
