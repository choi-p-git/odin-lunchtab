from __future__ import annotations

import csv
from pathlib import Path

import pytest

from odin_lunchtab.exception_candidates import (
    CANDIDATE_REPORT_NAME,
    write_manual_review_candidate_report,
)
from odin_lunchtab.sandbox_data import generate_sandbox_pack, preset_config
from odin_lunchtab.workflow import run_workflow


EXCEPTION_HEADERS = [
    "Reason",
    "Account Type",
    "ID Number",
    "Balance",
    "Student",
    "Candidate LoginBarcodes",
    "Candidate Names",
    "Attempted Rules",
    "Transformed Values",
]
LUNCHTAB_HEADERS = [
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "DefaultFamilyCode",
    "DefaultFamilyBalanceAmount",
    "ExternalId",
    "EmailAddress",
]


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def lunchtab_user(
    barcode: str,
    *,
    first: str,
    surname: str,
    preferred: str = "",
    external_id: str = "",
    email: str = "",
) -> dict[str, str]:
    return {
        "FirstName": first,
        "PreferredName": preferred,
        "Surname": surname,
        "LoginBarcode": barcode,
        "DefaultFamilyCode": f"F-{barcode}",
        "DefaultFamilyBalanceAmount": "0",
        "ExternalId": external_id,
        "EmailAddress": email,
    }


def exception_row(
    *,
    reason: str = "identifier matched but name validation failed",
    odin_id: str = "100",
    student: str = "Garcia, Ellie",
    candidates: str = "",
) -> dict[str, str]:
    return {
        "Reason": reason,
        "Account Type": "Student",
        "ID Number": odin_id,
        "Balance": "12.25",
        "Student": student,
        "Candidate LoginBarcodes": candidates,
        "Candidate Names": "",
        "Attempted Rules": "LoginBarcode",
        "Transformed Values": odin_id,
    }


def transfer_row(
    barcode: str,
    *,
    balance: str = "",
    family_code: str | None = None,
) -> dict[str, str]:
    return {
        "FirstName": "Elizabeth",
        "PreferredName": "Ellie",
        "Surname": "Garcia",
        "LoginBarcode": barcode,
        "DefaultFamilyCode": family_code or f"F-{barcode}",
        "DefaultFamilyBalanceAmount": "0",
        "OdinBalanceAmount": balance,
    }


def test_candidate_report_ranks_preferred_name_and_identifier_evidence(
    tmp_path: Path,
) -> None:
    exceptions = tmp_path / "manual exceptions.csv"
    users = tmp_path / "lunchtab.csv"
    write_csv(
        exceptions,
        EXCEPTION_HEADERS,
        [exception_row(odin_id="100", student="Garcia, Ellie", candidates="100")],
    )
    write_csv(
        users,
        LUNCHTAB_HEADERS,
        [
            lunchtab_user("999", first="Ell", surname="Garcia"),
            lunchtab_user("100", first="Elizabeth", preferred="Ellie", surname="Garcia"),
        ],
    )

    summary = write_manual_review_candidate_report(
        manual_review_exceptions_path=exceptions,
        lunchtab_path=users,
        output_dir=tmp_path / "out",
    )

    assert summary.exception_rows == 1
    assert summary.exceptions_with_candidates == 1
    assert summary.candidate_rows == 2
    rows = read_rows(tmp_path / "out" / CANDIDATE_REPORT_NAME)
    assert rows[0]["Candidate LoginBarcode"] == "100"
    assert rows[0]["Confidence"] == "High"
    assert "LoginBarcode equals Odin ID" in rows[0]["Evidence"]
    assert "preferred name matches" in rows[0]["Evidence"]
    assert rows[1]["Candidate LoginBarcode"] == "999"


def test_candidate_report_traces_candidates_to_transfer_rows(tmp_path: Path) -> None:
    exceptions = tmp_path / "manual exceptions.csv"
    users = tmp_path / "lunchtab.csv"
    transfer = tmp_path / "transfer.csv"
    transfer_headers = [
        "FirstName",
        "PreferredName",
        "Surname",
        "LoginBarcode",
        "DefaultFamilyCode",
        "DefaultFamilyBalanceAmount",
        "OdinBalanceAmount",
    ]
    write_csv(
        exceptions,
        EXCEPTION_HEADERS,
        [exception_row(odin_id="100", student="Garcia, Ellie", candidates="100")],
    )
    write_csv(
        users,
        LUNCHTAB_HEADERS,
        [lunchtab_user("100", first="Elizabeth", preferred="Ellie", surname="Garcia")],
    )
    write_csv(
        transfer,
        transfer_headers,
        [transfer_row("050"), transfer_row("100", balance="")],
    )

    summary = write_manual_review_candidate_report(
        manual_review_exceptions_path=exceptions,
        lunchtab_path=users,
        output_dir=tmp_path / "out",
        transfer_path=transfer,
    )

    rows = read_rows(summary.output_path)
    assert rows[0]["Transfer RowNumber"] == "3"
    assert rows[0]["Transfer Current OdinBalanceAmount"] == ""
    assert rows[0]["Suggested OdinBalanceAmount"] == "12.25"
    assert rows[0]["Transfer TraceStatus"] == "found unique transfer row"


def test_candidate_report_validates_required_columns(tmp_path: Path) -> None:
    exceptions = tmp_path / "bad exceptions.csv"
    users = tmp_path / "lunchtab.csv"
    write_csv(exceptions, ["Reason"], [{"Reason": "manual"}])
    write_csv(
        users,
        LUNCHTAB_HEADERS,
        [lunchtab_user("100", first="Ava", surname="Smith")],
    )

    with pytest.raises(ValueError, match="missing required columns"):
        write_manual_review_candidate_report(
            manual_review_exceptions_path=exceptions,
            lunchtab_path=users,
            output_dir=tmp_path / "out",
        )


def test_candidate_report_uses_sandbox_generated_exception_artifacts(
    tmp_path: Path,
) -> None:
    pack = generate_sandbox_pack(preset_config("Reconciliation exceptions", output_root=tmp_path))
    reconciliation = run_workflow(
        raw_data_dir=pack.run_dir,
        output_dir=tmp_path / "reconciliation",
        odin_path=pack.paths.odin_workbook,
        lunchtab_path=pack.paths.lunchtab_users,
    )
    assert reconciliation.output_paths.candidate_matches is not None
    assert reconciliation.output_paths.candidate_matches.is_file()

    summary = write_manual_review_candidate_report(
        manual_review_exceptions_path=reconciliation.output_paths.manual_review_exceptions,
        lunchtab_path=pack.paths.lunchtab_users,
        output_dir=tmp_path / "candidate-report",
    )

    assert summary.exception_rows == reconciliation.manual_review_exceptions
    assert summary.candidate_rows > 0
    assert summary.exceptions_with_candidates > 0
    rows = read_rows(summary.output_path)
    assert {row["SourceArtifact"] for row in rows} == {
        reconciliation.output_paths.manual_review_exceptions.name
    }
    assert {row["Transfer TraceStatus"] for row in rows} == {"not requested"}
    workflow_rows = read_rows(reconciliation.output_paths.candidate_matches)
    assert any(row["Transfer RowNumber"] for row in workflow_rows)
    assert {row["Transfer TraceStatus"] for row in workflow_rows} <= {
        "found unique transfer row",
        "candidate not found in transfer",
        "duplicate LoginBarcode in transfer",
    }
