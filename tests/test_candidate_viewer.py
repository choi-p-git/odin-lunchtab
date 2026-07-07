from __future__ import annotations

import csv
from pathlib import Path

import pytest

from odin_lunchtab.candidate_viewer import (
    AMBIGUOUS_EDIT_CHECKLIST_NAME,
    MANUAL_EDIT_CHECKLIST_NAME,
    PROPOSED_TRANSFER_AUDIT_NAME,
    PROPOSED_TRANSFER_NAME,
    filter_candidate_match_rows,
    load_candidate_match_rows,
    read_candidate_selection_values,
    summarize_candidate_match_rows,
    validate_candidate_selection_file,
    validate_candidate_selections,
    write_manual_edit_checklists,
    write_proposed_transfer_from_selections,
)
from odin_lunchtab.exception_candidates import CANDIDATE_HEADERS


def write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


TRANSFER_HEADERS = [
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "DefaultFamilyCode",
    "DefaultFamilyBalanceAmount",
    "OdinBalanceAmount",
]


def write_transfer(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TRANSFER_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


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
    transfer_row_number: str = "7",
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
        "Transfer RowNumber": transfer_row_number,
        "Transfer Current OdinBalanceAmount": current_balance,
        "Suggested OdinBalanceAmount": "12.25",
        "Transfer TraceStatus": trace_status,
        "Score": "95" if confidence == "High" else "75",
        "Evidence": evidence,
        "SourceArtifact": "Manual Review Exceptions.csv",
        "Notes": "Advisory candidate only.",
    }


def transfer_row(barcode: str, *, balance: str = "") -> dict[str, str]:
    return {
        "FirstName": "Ava",
        "PreferredName": "",
        "Surname": "Smith",
        "LoginBarcode": barcode,
        "DefaultFamilyCode": f"F-{barcode}",
        "DefaultFamilyBalanceAmount": "0",
        "OdinBalanceAmount": balance,
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
                transfer_row_number="3",
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


def test_candidate_viewer_exports_manual_edit_checklists(tmp_path: Path) -> None:
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
                transfer_row_number="3",
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

    output = write_manual_edit_checklists(
        load_candidate_match_rows(report),
        output_dir=tmp_path / "checklists",
    )

    ready_rows = read_csv_rows(tmp_path / "checklists" / MANUAL_EDIT_CHECKLIST_NAME)
    ambiguous_rows = read_csv_rows(tmp_path / "checklists" / AMBIGUOUS_EDIT_CHECKLIST_NAME)
    assert output.actionable_rows == 1
    assert output.ambiguous_rows == 2
    assert [row["Candidate LoginBarcode"] for row in ready_rows] == ["200"]
    assert {row["Candidate LoginBarcode"] for row in ambiguous_rows} == {"100", "101"}
    assert ready_rows[0]["ReviewCategory"] == "Ready - single actionable candidate"
    assert "edit transfer row 3" in ready_rows[0]["ManualAction"]


def test_candidate_selection_validator_accepts_one_choice_per_ambiguous_group(
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
        ],
    )
    rows = load_candidate_match_rows(report)

    validation = validate_candidate_selections(rows, {"100": "yes", "101": ""})

    assert not validation.blocked
    assert [row.login_barcode for row in validation.selected_rows] == ["100"]
    assert validation.issues == ()


def test_candidate_selection_validator_blocks_missing_and_multiple_ambiguous_choices(
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
        ],
    )
    rows = load_candidate_match_rows(report)

    missing = validate_candidate_selections(rows, {})
    multiple = validate_candidate_selections(rows, {"100": "x", "101": "selected"})

    assert missing.blocked
    assert [issue.issue_type for issue in missing.issues] == ["ambiguous group missing selection"]
    assert multiple.blocked
    assert [issue.issue_type for issue in multiple.issues] == ["multiple selections for group"]


def test_candidate_selection_validator_blocks_non_actionable_unknown_and_invalid_values(
    tmp_path: Path,
) -> None:
    report = tmp_path / "candidates.csv"
    write_candidates(
        report,
        [
            candidate_row(
                confidence="Low",
                odin_student="Jones, Max",
                barcode="300",
                candidate_name="Jones, Max",
                evidence="first initial matches",
                trace_status="candidate not found in transfer",
            ),
            candidate_row(
                confidence="High",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="first name matches",
                transfer_row_number="3",
            ),
        ],
    )
    rows = load_candidate_match_rows(report)

    validation = validate_candidate_selections(
        rows,
        {"300": "yes", "404": "yes", "200": "maybe"},
    )

    assert validation.blocked
    assert [issue.issue_type for issue in validation.issues] == [
        "non-actionable selected",
        "unknown candidate",
        "invalid selection value",
    ]


def test_candidate_selection_file_reader_and_validator(tmp_path: Path) -> None:
    report = tmp_path / "candidates.csv"
    write_candidates(
        report,
        [
            candidate_row(
                confidence="High",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="first name matches",
                transfer_row_number="3",
            ),
        ],
    )
    output = write_manual_edit_checklists(
        load_candidate_match_rows(report),
        output_dir=tmp_path / "checklists",
    )
    rows = read_csv_rows(output.actionable_path)
    rows[0]["Selected"] = "yes"
    with output.actionable_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    selections = read_candidate_selection_values(output.actionable_path)
    validation = validate_candidate_selection_file(
        load_candidate_match_rows(report),
        output.actionable_path,
    )

    assert selections == {"200": "yes"}
    assert not validation.blocked
    assert [row.login_barcode for row in validation.selected_rows] == ["200"]


def test_write_proposed_transfer_applies_valid_selected_candidates_to_copy(
    tmp_path: Path,
) -> None:
    report = tmp_path / "candidates.csv"
    transfer = tmp_path / "transfer.csv"
    write_candidates(
        report,
        [
            candidate_row(
                confidence="High",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="first name matches",
                transfer_row_number="3",
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
    write_transfer(transfer, [transfer_row("100"), transfer_row("200"), transfer_row("300")])

    output = write_proposed_transfer_from_selections(
        transfer_path=transfer,
        candidate_rows=load_candidate_match_rows(report),
        selections={"200": "yes"},
        output_dir=tmp_path / "proposed",
    )

    original_rows = read_csv_rows(transfer)
    proposed_rows = read_csv_rows(tmp_path / "proposed" / PROPOSED_TRANSFER_NAME)
    audit_rows = read_csv_rows(tmp_path / "proposed" / PROPOSED_TRANSFER_AUDIT_NAME)
    assert output.updated_rows == 1
    assert original_rows[1]["OdinBalanceAmount"] == ""
    assert proposed_rows[1]["OdinBalanceAmount"] == "12.25"
    assert proposed_rows[0]["OdinBalanceAmount"] == ""
    assert audit_rows[0]["Candidate LoginBarcode"] == "200"
    assert audit_rows[0]["Status"] == "UPDATED"


def test_write_proposed_transfer_blocks_invalid_selection_and_stale_transfer(
    tmp_path: Path,
) -> None:
    report = tmp_path / "candidates.csv"
    transfer = tmp_path / "transfer.csv"
    write_candidates(
        report,
        [
            candidate_row(
                confidence="High",
                odin_student="Smith, Ava",
                barcode="200",
                candidate_name="Smith, Ava",
                evidence="first name matches",
                transfer_row_number="3",
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
    rows = load_candidate_match_rows(report)
    write_transfer(transfer, [transfer_row("100"), transfer_row("200", balance="9.00")])

    with pytest.raises(ValueError, match="non-actionable selected"):
        write_proposed_transfer_from_selections(
            transfer_path=transfer,
            candidate_rows=rows,
            selections={"300": "yes"},
            output_dir=tmp_path / "bad-selection",
        )
    with pytest.raises(ValueError, match="already has OdinBalanceAmount"):
        write_proposed_transfer_from_selections(
            transfer_path=transfer,
            candidate_rows=rows,
            selections={"200": "yes"},
            output_dir=tmp_path / "stale",
        )


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
