from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from odin_lunchtab.manual_reconciliation import (
    DELTA_AUDIT_NAME,
    DELTA_SUMMARY_NAME,
    audit_manual_reconciliation,
    run_manual_reconciliation_workflow,
)
from odin_lunchtab.sandbox_data import generate_sandbox_pack, preset_config
from odin_lunchtab.workflow import run_workflow


HEADERS = [
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "DefaultFamilyCode",
    "DefaultFamilyBalanceAmount",
    "OdinBalanceAmount",
    "ExtraColumn",
]


def write_transfer(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def row(
    barcode: str,
    *,
    balance: str = "",
    family_code: str | None = None,
    first_name: str = "Ava",
    extra: str = "preserved",
) -> dict[str, str]:
    return {
        "FirstName": first_name,
        "PreferredName": "",
        "Surname": "Smith",
        "LoginBarcode": barcode,
        "DefaultFamilyCode": family_code or f"F-{barcode}",
        "DefaultFamilyBalanceAmount": "0",
        "OdinBalanceAmount": balance,
        "ExtraColumn": extra,
    }


def test_audit_records_manual_resolutions_without_flagging_unchanged_matches(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original.csv"
    edited = tmp_path / "edited.csv"
    output = tmp_path / "audit"
    write_transfer(
        original,
        [
            row("001", balance="6.50"),
            row("002"),
        ],
    )
    write_transfer(
        edited,
        [
            row("001", balance="6.50"),
            row("002", balance="4.25"),
        ],
    )

    summary = audit_manual_reconciliation(
        original_transfer_path=original,
        edited_transfer_path=edited,
        output_dir=output,
    )

    assert summary.status == "PASS"
    assert summary.unchanged_automated_matches == 1
    assert summary.manual_resolutions == 1
    assert summary.changed_automated_balances == 0
    assert summary.output_paths.delta_audit == output / DELTA_AUDIT_NAME
    audit_rows = read_rows(output / DELTA_AUDIT_NAME)
    assert audit_rows == [
        {
            "ChangeType": "manual resolution",
            "Severity": "REVIEW",
            "RowNumber": "3",
            "FieldName": "OdinBalanceAmount",
            "OriginalValue": "",
            "EditedValue": "4.25",
            "Identifier": "LoginBarcode=002",
            "Notes": "Previously unresolved row now has a manually supplied balance.",
        }
    ]
    summary_text = (output / DELTA_SUMMARY_NAME).read_text(encoding="utf-8")
    assert "Status: PASS" in summary_text


def test_audit_flags_risky_balance_family_and_identity_edits(tmp_path: Path) -> None:
    original = tmp_path / "original.csv"
    edited = tmp_path / "edited.csv"
    output = tmp_path / "audit"
    write_transfer(
        original,
        [
            row("001", balance="6.50"),
            row("002", balance="3.00"),
        ],
    )
    write_transfer(
        edited,
        [
            row("001", balance="7.00", family_code="F-999"),
            row("002", balance="", first_name="Legal"),
        ],
    )

    summary = audit_manual_reconciliation(
        original_transfer_path=original,
        edited_transfer_path=edited,
        output_dir=output,
    )

    assert summary.status == "REVIEW"
    assert summary.changed_automated_balances == 1
    assert summary.cleared_automated_balances == 1
    assert summary.family_code_changes == 1
    assert summary.identity_field_changes == 1
    audit_rows = read_rows(output / DELTA_AUDIT_NAME)
    assert {row["ChangeType"] for row in audit_rows} == {
        "changed automated balance",
        "cleared automated balance",
        "family code changed",
        "identity field changed",
    }
    assert {row["Severity"] for row in audit_rows} == {"HIGH"}


def test_audit_blocks_invalid_manual_amount(tmp_path: Path) -> None:
    original = tmp_path / "original.csv"
    edited = tmp_path / "edited.csv"
    output = tmp_path / "audit"
    write_transfer(original, [row("001")])
    write_transfer(edited, [row("001", balance="bad")])

    summary = audit_manual_reconciliation(
        original_transfer_path=original,
        edited_transfer_path=edited,
        output_dir=output,
    )

    assert summary.status == "BLOCKED"
    assert summary.invalid_manual_amounts == 1
    audit_rows = read_rows(output / DELTA_AUDIT_NAME)
    assert audit_rows[0]["ChangeType"] == "invalid manual amount"
    assert audit_rows[0]["Severity"] == "BLOCKING"


def test_audit_rejects_structural_mismatches(tmp_path: Path) -> None:
    original = tmp_path / "original.csv"
    edited = tmp_path / "edited.csv"
    output = tmp_path / "audit"
    write_transfer(original, [row("001")])
    with edited.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["LoginBarcode", "OdinBalanceAmount"])
        writer.writeheader()
        writer.writerow({"LoginBarcode": "001", "OdinBalanceAmount": "5"})

    with pytest.raises(ValueError, match="headers must match"):
        audit_manual_reconciliation(
            original_transfer_path=original,
            edited_transfer_path=edited,
            output_dir=output,
        )


def test_managed_manual_review_writes_timestamped_manifest(tmp_path: Path) -> None:
    original = tmp_path / "original.csv"
    edited = tmp_path / "edited.csv"
    write_transfer(original, [row("001"), row("002", balance="3.25")])
    write_transfer(edited, [row("001", balance="5.00"), row("002", balance="3.25")])

    result = run_manual_reconciliation_workflow(
        original_transfer_path=original,
        edited_transfer_path=edited,
        output_root=tmp_path / "reviews",
    )

    assert result.run_dir.is_dir()
    assert result.summary.output_paths.delta_audit.is_file()
    assert result.summary.output_paths.summary.is_file()
    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["workflow"] == "Manual Reconciliation Review"
    assert manifest["review_status"] == "PASS"
    assert manifest["inputs"]["original_transfer"]["name"] == original.name
    assert str(tmp_path) not in result.manifest_path.read_text(encoding="utf-8")


def test_manual_review_audits_sandbox_generated_reconciliation_transfer(
    tmp_path: Path,
) -> None:
    pack = generate_sandbox_pack(preset_config("Clean baseline", output_root=tmp_path))
    reconciliation = run_workflow(
        raw_data_dir=pack.run_dir,
        output_dir=tmp_path / "reconciliation",
        odin_path=pack.paths.odin_workbook,
        lunchtab_path=pack.paths.lunchtab_users,
    )
    original = reconciliation.output_paths.transfer
    headers, rows = csv_rows(original)
    edited = tmp_path / "edited transfer.csv"

    unresolved = next(row for row in rows if not row["OdinBalanceAmount"].strip())
    unresolved["OdinBalanceAmount"] = "8.75"
    with edited.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    summary = audit_manual_reconciliation(
        original_transfer_path=original,
        edited_transfer_path=edited,
        output_dir=tmp_path / "manual-review",
    )

    assert summary.status == "PASS"
    assert summary.manual_resolutions == 1
    assert summary.unchanged_automated_matches == pack.expected.matched_rows
    audit_rows = read_rows(summary.output_paths.delta_audit)
    assert audit_rows[0]["ChangeType"] == "manual resolution"
