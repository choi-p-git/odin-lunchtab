from __future__ import annotations

import csv
from pathlib import Path

import pytest

from odin_lunchtab.candidate_viewer import (
    filter_candidate_match_rows,
    load_candidate_match_rows,
    summarize_candidate_match_rows,
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
    odin_id: str | None = None,
    current_balance: str = "",
    trace_status: str = "found unique transfer row",
) -> dict[str, str]:
    return {
        "Reason": "identifier matched but name validation failed",
        "Odin ID Number": odin_id or barcode,
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
        "Transfer Current OdinBalanceAmount": current_balance,
        "Suggested OdinBalanceAmount": "12.25",
        "Transfer TraceStatus": trace_status,
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
                current_balance="4.00",
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
    assert filter_candidate_match_rows(rows, actionable_only=True) == [rows[0]]


def test_candidate_viewer_summarizes_actionable_confidence_and_trace_counts(
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
            ),
            candidate_row(
                confidence="Medium",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="surname matches",
                current_balance="4.00",
            ),
            candidate_row(
                confidence="Low",
                odin_student="Jones, Max",
                barcode="300",
                candidate_name="Jones, Max",
                evidence="first initial matches",
                trace_status="candidate not found in transfer",
            ),
        ],
    )

    summary = summarize_candidate_match_rows(load_candidate_match_rows(report))

    assert summary.total_rows == 3
    assert summary.actionable_rows == 1
    assert summary.confidence_counts == {"High": 1, "Low": 1, "Medium": 1}
    assert summary.trace_status_counts == {
        "candidate not found in transfer": 1,
        "found unique transfer row": 2,
    }


def test_candidate_viewer_flags_ambiguous_actionable_groups(tmp_path: Path) -> None:
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
                rank="1",
                odin_id="999",
            ),
            candidate_row(
                confidence="Medium",
                odin_student="Garcia, Ellie",
                barcode="101",
                candidate_name="Garcia, Ellie",
                evidence="first name matches",
                rank="2",
                odin_id="999",
            ),
            candidate_row(
                confidence="High",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="first name matches",
            ),
        ],
    )

    rows = load_candidate_match_rows(report)
    summary = summarize_candidate_match_rows(rows)

    assert [row.actionable_group_count for row in rows] == [2, 2, 1]
    assert [row.actionable_group_position for row in rows] == [1, 2, 1]
    assert [row.has_ambiguous_actionable_group for row in rows] == [True, True, False]
    assert filter_candidate_match_rows(rows, ambiguous_only=True) == rows[:2]
    assert summary.actionable_rows == 3
    assert summary.ambiguous_actionable_rows == 2
    assert summary.ambiguous_actionable_groups == 1


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
    assert "Actionable candidate group: 1 of 1" in row.detail_text
    assert "Ambiguity: none detected for actionable candidates" in row.detail_text
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
