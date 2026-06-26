from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from odin_lunchtab.audit_control import INITIAL_BALANCES_AUDIT_CONTROL_NAME
from odin_lunchtab.initial_balances import (
    AUDIT_OUTPUT_NAME,
    EXCEPTIONS_OUTPUT_NAME,
    inspect_initial_balances_inputs,
    process_initial_balances,
    run_initial_balances_workflow,
)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_transfer(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv(
        path,
        ["DefaultFamilyCode", "OdinBalanceAmount", "StudentColumn"],
        rows,
    )


def write_initial(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv(path, ["FamilyName", "FamilyCode", "Amount"], rows)


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def test_process_aggregates_adds_and_preserves_target_rows(tmp_path: Path) -> None:
    transfer = tmp_path / "transfer.csv"
    initial = tmp_path / "InitialBalances.csv"
    output = tmp_path / "output"
    write_transfer(
        transfer,
        [
            {
                "DefaultFamilyCode": " 001 ",
                "OdinBalanceAmount": "2.50",
                "StudentColumn": "private",
            },
            {
                "DefaultFamilyCode": "001",
                "OdinBalanceAmount": "-1",
                "StudentColumn": "private",
            },
            {
                "DefaultFamilyCode": "A-2",
                "OdinBalanceAmount": "0",
                "StudentColumn": "private",
            },
            {
                "DefaultFamilyCode": "unused",
                "OdinBalanceAmount": "",
                "StudentColumn": "private",
            },
        ],
    )
    write_initial(
        initial,
        [
            {"FamilyName": "One", "FamilyCode": "001", "Amount": "10.00"},
            {"FamilyName": "Two", "FamilyCode": "A-2", "Amount": ""},
            {"FamilyName": "Untouched", "FamilyCode": "003", "Amount": "4.25"},
        ],
    )

    summary = process_initial_balances(
        transfer_path=transfer,
        initial_balances_path=initial,
        output_dir=output,
    )

    assert not summary.blocked
    assert summary.populated_balance_rows == 3
    assert summary.matched_source_rows == 3
    assert summary.updated_families == 2
    assert summary.source_total == "1.50"
    assert summary.applied_total == "1.50"
    assert summary.output_paths.processed == output / "Processed - InitialBalances.csv"
    assert summary.audit_control_status == "PASS"
    assert summary.output_paths.audit_control == output / INITIAL_BALANCES_AUDIT_CONTROL_NAME
    headers, rows = read_rows(summary.output_paths.processed)
    assert headers == ["FamilyName", "FamilyCode", "Amount"]
    assert [row["Amount"] for row in rows] == ["11.50", "0", "4.25"]
    _, audit = read_rows(output / AUDIT_OUTPUT_NAME)
    assert audit[0] == {
        "FamilyCode": "001",
        "SourceRowCount": "2",
        "OriginalAmount": "10.00",
        "AggregatedOdinAmount": "1.50",
        "FinalAmount": "11.50",
        "Status": "updated",
    }
    _, control_rows = read_rows(output / INITIAL_BALANCES_AUDIT_CONTROL_NAME)
    assert {
        (row["Category"], row["Subcategory"], row["RowCount"], row["AmountTotal"])
        for row in control_rows
    } >= {
        ("Source", "Valid populated transfer rows", "3", "1.50"),
        ("Applied", "Updated InitialBalances families", "3", "1.50"),
        ("Control Total", "Valid source = applied + blocked valid balances", "3", "1.50"),
        (
            "Control Total",
            "Final matched total - original matched total = applied total",
            "3",
            "1.50",
        ),
    }
    assert {row["ControlStatus"] for row in control_rows} == {"PASS"}


@pytest.mark.parametrize(
    ("transfer_rows", "initial_rows", "reason"),
    [
        (
            [{"DefaultFamilyCode": "", "OdinBalanceAmount": "5", "StudentColumn": ""}],
            [{"FamilyName": "One", "FamilyCode": "001", "Amount": "0"}],
            "blank DefaultFamilyCode",
        ),
        (
            [{"DefaultFamilyCode": "001", "OdinBalanceAmount": "bad", "StudentColumn": ""}],
            [{"FamilyName": "One", "FamilyCode": "001", "Amount": "0"}],
            "invalid OdinBalanceAmount",
        ),
        (
            [{"DefaultFamilyCode": "999", "OdinBalanceAmount": "5", "StudentColumn": ""}],
            [{"FamilyName": "One", "FamilyCode": "001", "Amount": "0"}],
            "not found",
        ),
        (
            [{"DefaultFamilyCode": "001", "OdinBalanceAmount": "5", "StudentColumn": ""}],
            [
                {"FamilyName": "One", "FamilyCode": "001", "Amount": "0"},
                {"FamilyName": "Duplicate", "FamilyCode": "001", "Amount": "2"},
            ],
            "duplicate FamilyCode",
        ),
        (
            [{"DefaultFamilyCode": "001", "OdinBalanceAmount": "5", "StudentColumn": ""}],
            [{"FamilyName": "One", "FamilyCode": "001", "Amount": "bad"}],
            "invalid target Amount",
        ),
    ],
)
def test_process_blocks_import_and_writes_exception_reports(
    tmp_path: Path,
    transfer_rows: list[dict[str, str]],
    initial_rows: list[dict[str, str]],
    reason: str,
) -> None:
    transfer = tmp_path / "transfer.csv"
    initial = tmp_path / "InitialBalances.csv"
    output = tmp_path / "output"
    write_transfer(transfer, transfer_rows)
    write_initial(initial, initial_rows)

    summary = process_initial_balances(
        transfer_path=transfer,
        initial_balances_path=initial,
        output_dir=output,
    )

    assert summary.blocked
    assert summary.output_paths.processed is None
    assert not (output / "Processed - InitialBalances.csv").exists()
    _, exceptions = read_rows(output / EXCEPTIONS_OUTPUT_NAME)
    assert any(reason in row["Reason"] for row in exceptions)
    assert (output / AUDIT_OUTPUT_NAME).is_file()
    assert (output / INITIAL_BALANCES_AUDIT_CONTROL_NAME).is_file()


def test_initial_balances_audit_control_reports_blocked_balances_without_double_counting(
    tmp_path: Path,
) -> None:
    transfer = tmp_path / "transfer.csv"
    initial = tmp_path / "InitialBalances.csv"
    output = tmp_path / "output"
    write_transfer(
        transfer,
        [
            {"DefaultFamilyCode": "001", "OdinBalanceAmount": "5", "StudentColumn": ""},
            {"DefaultFamilyCode": "001", "OdinBalanceAmount": "-2", "StudentColumn": ""},
            {"DefaultFamilyCode": "", "OdinBalanceAmount": "7", "StudentColumn": ""},
            {"DefaultFamilyCode": "bad", "OdinBalanceAmount": "not-money", "StudentColumn": ""},
        ],
    )
    write_initial(
        initial,
        [
            {"FamilyName": "One", "FamilyCode": "001", "Amount": "bad"},
            {"FamilyName": "Duplicate", "FamilyCode": "001", "Amount": "0"},
        ],
    )

    summary = process_initial_balances(
        transfer_path=transfer,
        initial_balances_path=initial,
        output_dir=output,
    )

    assert summary.blocked
    assert summary.audit_control_status == "PASS"
    _, control_rows = read_rows(output / INITIAL_BALANCES_AUDIT_CONTROL_NAME)
    blocked_rows = [row for row in control_rows if row["Category"] == "Blocked Balance"]
    assert {(row["Subcategory"], row["RowCount"], row["AmountTotal"]) for row in blocked_rows} == {
        (
            "duplicate FamilyCode in InitialBalances | invalid target Amount",
            "2",
            "3",
        ),
        ("populated balance has blank DefaultFamilyCode", "1", "7"),
    }
    assert (
        next(
            row
            for row in control_rows
            if row["Subcategory"] == "Valid source = applied + blocked valid balances"
        )["AmountTotal"]
        == "10"
    )
    assert {row["ControlStatus"] for row in control_rows} == {"PASS"}


def test_inspection_rejects_noncanonical_initial_balances_headers(tmp_path: Path) -> None:
    transfer = tmp_path / "transfer.csv"
    initial = tmp_path / "InitialBalances.csv"
    write_transfer(transfer, [])
    write_csv(initial, ["FamilyCode", "FamilyName", "Amount"], [])

    with pytest.raises(ValueError, match="exactly these columns in order"):
        inspect_initial_balances_inputs(transfer, initial)


def test_managed_run_publishes_clean_or_blocked_run_atomically(tmp_path: Path) -> None:
    transfer = tmp_path / "transfer.csv"
    initial = tmp_path / "InitialBalances.csv"
    results = tmp_path / "results"
    write_transfer(
        transfer,
        [{"DefaultFamilyCode": "001", "OdinBalanceAmount": "5", "StudentColumn": "Alaná"}],
    )
    transfer.write_bytes(transfer.read_text(encoding="utf-8-sig").encode("cp1252"))
    write_initial(
        initial,
        [{"FamilyName": "One", "FamilyCode": "001", "Amount": "2"}],
    )
    moments = iter(
        [
            datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 24, 12, 1, tzinfo=timezone.utc),
        ]
    )

    result = run_initial_balances_workflow(
        transfer_path=transfer,
        initial_balances_path=initial,
        output_root=results,
        now=lambda: next(moments),
    )

    assert result.run_dir.name == "2026-06-24_120000"
    assert result.summary.output_paths.processed is not None
    assert result.summary.output_paths.processed.is_file()
    assert result.summary.output_paths.audit_control is not None
    assert result.summary.output_paths.audit_control.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["inputs"] == {
        "reconciled_transfer": {
            "name": "transfer.csv",
            "encoding": "Windows-1252",
            "used_fallback": True,
        },
        "initial_balances": {
            "name": "InitialBalances.csv",
            "encoding": "UTF-8 with BOM",
            "used_fallback": False,
        },
    }
    assert manifest["audit_control"] == {
        "status": "PASS",
        "report": INITIAL_BALANCES_AUDIT_CONTROL_NAME,
    }
    assert "001" not in result.manifest_path.read_text(encoding="utf-8")
    assert result.summary.output_paths.processed.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not list(results.glob(".staging-*"))

    write_transfer(
        transfer,
        [{"DefaultFamilyCode": "missing", "OdinBalanceAmount": "5", "StudentColumn": ""}],
    )
    blocked_moments = iter(
        [
            datetime(2026, 6, 24, 13, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 24, 13, 1, tzinfo=timezone.utc),
        ]
    )
    blocked = run_initial_balances_workflow(
        transfer_path=transfer,
        initial_balances_path=initial,
        output_root=results,
        now=lambda: next(blocked_moments),
    )

    assert blocked.summary.blocked
    assert blocked.summary.output_paths.processed is None
    assert blocked.summary.output_paths.audit.is_file()
    assert blocked.summary.output_paths.exceptions.is_file()
    assert blocked.manifest_path.is_file()
    assert not list(results.glob(".staging-*"))
