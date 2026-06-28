from __future__ import annotations

import csv
from pathlib import Path

import pytest

from odin_lunchtab.candidate_viewer import (
    filter_candidate_match_rows,
    load_candidate_match_rows,
)
from odin_lunchtab.exception_candidates import CANDIDATE_HEADERS


def write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def candidate_row(
    *,
    confidence: str,
    odin_student: str,
    barcode: str,
    candidate_name: str,
    evidence: str,
    rank: str = "1",
) -> dict[str, str]:
    return {
        "Reason": "identifier matched but name validation failed",
        "Odin ID Number": barcode,
        "Odin Student": odin_student,
        "Odin Balance": "12.25",
        "Candidate Rank": rank,
        "Confidence": confidence,
        "Candidate LoginBarcode": barcode,
        "Candidate ExternalId": "",
        "Candidate FamilyCode": f"F-{barcode}",
        "Candidate Name": candidate_name,
        "Candidate EmailAddress": f"{barcode}@sandbox.invalid",
        "Transfer RowNumber": "7",
        "Transfer Current OdinBalanceAmount": "",
        "Suggested OdinBalanceAmount": "12.25",
        "Transfer TraceStatus": "found unique transfer row",
        "Score": "95" if confidence == "High" else "75",
        "Evidence": evidence,
        "SourceArtifact": "Manual Review Exceptions.csv",
        "Notes": "Advisory candidate only.",
    }


def test_candidate_viewer_loads_and_filters_rows(tmp_path: Path) -> None:
    report = tmp_path / "candidates.csv"
    write_candidates(
        report,
        [
            candidate_row(
                confidence="High",
                odin_student="Garcia, Ellie",
                barcode="100",
                candidate_name="Garcia, Elizabeth (Ellie)",
                evidence="LoginBarcode equals Odin ID | preferred name matches",
            ),
            candidate_row(
                confidence="Medium",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="surname matches | first name matches",
                rank="2",
            ),
        ],
    )

    rows = load_candidate_match_rows(report)

    assert len(rows) == 2
    assert rows[0].candidate_name == "Garcia, Elizabeth (Ellie)"
    assert filter_candidate_match_rows(rows, query="ellie preferred") == [rows[0]]
    assert filter_candidate_match_rows(rows, confidence="Medium") == [rows[1]]
    assert filter_candidate_match_rows(rows, query="garcia", confidence="High") == [rows[0]]
    assert filter_candidate_match_rows(rows, query="row") == rows


def test_candidate_viewer_detail_text_contains_copyable_audit_context(
    tmp_path: Path,
) -> None:
    report = tmp_path / "candidates.csv"
    write_candidates(
        report,
        [
            candidate_row(
                confidence="High",
                odin_student="Garcia, Ellie",
                barcode="100",
                candidate_name="Garcia, Elizabeth (Ellie)",
                evidence="preferred name matches",
            )
        ],
    )

    row = load_candidate_match_rows(report)[0]

    assert "Odin Student: Garcia, Ellie" in row.detail_text
    assert "LoginBarcode: 100" in row.detail_text
    assert "Transfer RowNumber: 7" in row.detail_text
    assert "Suggested OdinBalanceAmount: 12.25" in row.detail_text
    assert "Evidence: preferred name matches" in row.detail_text


def test_candidate_viewer_rejects_wrong_report_schema(tmp_path: Path) -> None:
    report = tmp_path / "bad.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["Reason"])
        writer.writeheader()
        writer.writerow({"Reason": "bad"})

    with pytest.raises(ValueError, match="missing required columns"):
        load_candidate_match_rows(report)
