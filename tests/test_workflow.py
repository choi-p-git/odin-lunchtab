from __future__ import annotations

import csv
import logging
from pathlib import Path

import pytest
from openpyxl import Workbook

from odin_lunchtab.workflow import (
    EXCEPTIONS_OUTPUT_NAME,
    FINAL_OUTPUT_NAME,
    MANUAL_REVIEW_EXCEPTIONS_OUTPUT_NAME,
    OdinRecord,
    extract_odin_report,
    match_balances,
    read_csv,
    read_csv_with_metadata,
    run_workflow,
    split_student_name,
)


def write_odin(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Account Balance Report"
    sheet.append(["Account Balance Report"])
    sheet.append(["As of 06-23-2026"])
    sheet.append([])
    sheet.append(["Account Type", "ID Number", "Deposits", "Spendings", "Balance", "Student"])
    for row in rows:
        sheet.append(row)
    sheet.append(["", "Patron Count:", len(rows)])
    sheet.append(["", "Total Deposits:", "999.00"])
    sheet.append(["Account Code", "Account Type", "Balance"])
    workbook.save(path)


def write_lunchtab(path: Path, rows: list[dict[str, str]]) -> None:
    headers = [
        "FirstName",
        "PreferredName",
        "Surname",
        "LoginBarcode",
        "DefaultFamilyCode",
        "DefaultFamilyBalanceAmount",
        "ExtraColumn",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def odin_record(
    id_number: str,
    student: str,
    balance: str = "12.34",
) -> OdinRecord:
    surname, first_name = split_student_name(student)
    return OdinRecord(
        account_type="Student Debit",
        id_number=id_number,
        deposits="20",
        spendings="7.66",
        balance=balance,
        student=student,
        surname=surname,
        first_name=first_name,
    )


def user(
    barcode: str,
    surname: str,
    first_name: str,
    preferred_name: str = "",
) -> dict[str, str]:
    return {
        "FirstName": first_name,
        "PreferredName": preferred_name,
        "Surname": surname,
        "LoginBarcode": barcode,
        "DefaultFamilyCode": f"F-{barcode}",
        "DefaultFamilyBalanceAmount": "0",
        "ExtraColumn": "preserved",
    }


def test_extracts_only_complete_patron_rows_and_preserves_leading_zero_id(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.xlsx"
    write_odin(
        report,
        [
            ["Student Debit", "00123", "10.50", "2.25", "8.25", "O'Brien, Mary K."],
            ["Faculty Debit", "44", "5", "0", "5", ""],
        ],
    )

    records, malformed = extract_odin_report(report)

    assert [record.id_number for record in records] == ["00123"]
    assert records[0].surname == "O'Brien"
    assert records[0].first_name == "Mary K."
    assert records[0].balance == "8.25"
    assert len(malformed) == 1
    assert malformed[0].reason == "missing one or more required Odin fields"


@pytest.mark.parametrize(
    ("encoding", "expected_label", "used_fallback"),
    [
        ("utf-8", "UTF-8", False),
        ("utf-8-sig", "UTF-8 with BOM", False),
        ("utf-16", "UTF-16 LE with BOM", False),
        ("utf-16-be", "UTF-16 BE with BOM", False),
        ("cp1252", "Windows-1252", True),
    ],
)
def test_read_csv_accepts_supported_encodings(
    tmp_path: Path,
    encoding: str,
    expected_label: str,
    used_fallback: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "export.csv"
    text = "Name,Identifier,Amount\r\nAlaná,001,5\r\n"
    if encoding == "utf-16-be":
        path.write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))
    else:
        path.write_bytes(text.encode(encoding))

    with caplog.at_level(logging.INFO, logger="odin_lunchtab"):
        headers, rows, metadata = read_csv_with_metadata(path)

    assert headers == ["Name", "Identifier", "Amount"]
    assert rows == [{"Name": "Alaná", "Identifier": "001", "Amount": "5"}]
    assert metadata.encoding == expected_label
    assert metadata.used_fallback is used_fallback
    assert f"encoding={expected_label}" in caplog.text
    assert f"fallback={used_fallback}" in caplog.text
    assert str(path) not in caplog.text


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"Name,Amount\r\nBad,\x81\r\n", "encoding is unsupported"),
        ("Name,Amount\r\nBad,\ufffd\r\n".encode(), "replacement characters"),
        (b"Name,Amount\r\nBad,\x00\r\n", "NUL bytes"),
        (b"Name,Amount\r\nBad,\x07\r\n", "control characters"),
        (b"\xff\xfe\x00\x00Name", "UTF-32"),
        ("Name,Amount\r\nBad,5\r\n".encode("utf-16-le"), "NUL bytes"),
        (b'Name,Amount\r\n"unterminated,5\r\n', "structure is malformed"),
    ],
)
def test_read_csv_rejects_unsafe_or_unsupported_content(
    tmp_path: Path,
    content: bytes,
    message: str,
) -> None:
    path = tmp_path / "unsafe.csv"
    path.write_bytes(content)

    with pytest.raises(ValueError, match=message):
        read_csv(path)


@pytest.mark.parametrize(
    ("student", "expected"),
    [
        ("Smith, Ava Marie J.", ("Smith", "Ava Marie J.")),
        ("García-Ruiz, Ana María", ("García-Ruiz", "Ana María")),
        ("O'Brien, Jo Ann", ("O'Brien", "Jo Ann")),
    ],
)
def test_splits_student_name_only_on_first_comma(student: str, expected: tuple[str, str]) -> None:
    assert split_student_name(student) == expected


def test_matches_unique_barcode_with_preferred_name_and_unique_name_fallback() -> None:
    users = [
        user("100", "Iverstine", "Gweneth", "Rose"),
        user("200", "Barbera", "Frances"),
        user("300", "Other", "Person"),
    ]
    records = [
        odin_record("100", "Iverstine, Rose", "4.50"),
        odin_record("old-id", "Barbera, Frances", "-2.00"),
    ]

    output, exceptions, counts = match_balances(records, users)

    assert [row["OdinBalanceAmount"] for row in output] == ["4.50", "-2.00", ""]
    assert output[2]["ExtraColumn"] == "preserved"
    assert exceptions == []
    assert counts == {"id": 1, "name": 1}


def test_name_matching_normalizes_accents_punctuation_and_initials() -> None:
    users = [
        user("100", "Garcia Ruiz", "Maria"),
        user("200", "O Brien", "Jillian"),
    ]
    records = [
        odin_record("100", "García-Ruiz, María Elena"),
        odin_record("200", "O'Brien, J."),
    ]

    output, exceptions, counts = match_balances(records, users)

    assert [row["OdinBalanceAmount"] for row in output] == ["12.34", "12.34"]
    assert exceptions == []
    assert counts == {"id": 2}


def test_quarantines_conflicts_ambiguous_names_and_unmatched_records() -> None:
    users = [
        user("100", "Correct", "Name"),
        user("201", "Brown", "Amy"),
        user("202", "Brown", "Amy"),
    ]
    records = [
        odin_record("100", "Wrong, Person"),
        odin_record("missing", "Brown, Amy"),
        odin_record("none", "Nobody, Here"),
    ]

    output, exceptions, counts = match_balances(records, users)

    assert all(row["OdinBalanceAmount"] == "" for row in output)
    assert counts == {}
    assert {row["Reason"] for row in exceptions} == {
        "barcode matched but name validation failed",
        "ambiguous name match",
        "no Lunchtab match",
    }
    ambiguous = next(row for row in exceptions if row["Reason"] == "ambiguous name match")
    assert ambiguous["Candidate LoginBarcodes"] == "201 | 202"


def test_quarantines_duplicate_lunchtab_barcodes() -> None:
    users = [
        user("100", "Smith", "Ava"),
        user("100", "Smith", "Ava"),
    ]

    output, exceptions, counts = match_balances([odin_record("100", "Smith, Ava")], users)

    assert all(row["OdinBalanceAmount"] == "" for row in output)
    assert counts == {}
    assert exceptions[0]["Reason"] == "duplicate Lunchtab LoginBarcode"
    assert exceptions[0]["Candidate LoginBarcodes"] == "100 | 100"


def test_quarantines_duplicate_odin_ids() -> None:
    users = [user("100", "Smith", "Ava")]
    records = [
        odin_record("100", "Smith, Ava"),
        odin_record("100", "Smith, Ava"),
    ]

    output, exceptions, counts = match_balances(records, users)

    assert output[0]["OdinBalanceAmount"] == ""
    assert counts == {}
    assert [row["Reason"] for row in exceptions].count("duplicate Odin ID Number") == 2


def test_quarantines_multiple_odin_records_targeting_one_lunchtab_user() -> None:
    users = [user("100", "Smith", "Ava")]
    records = [
        odin_record("legacy-one", "Smith, Ava"),
        odin_record("legacy-two", "Smith, Ava"),
    ]

    output, exceptions, counts = match_balances(records, users)

    assert output[0]["OdinBalanceAmount"] == ""
    assert counts == {}
    assert [row["Reason"] for row in exceptions] == [
        "multiple Odin records matched one Lunchtab user",
        "multiple Odin records matched one Lunchtab user",
    ]


def test_end_to_end_writes_expected_files_columns_and_rows(tmp_path: Path) -> None:
    raw = tmp_path / "Raw Data"
    output = tmp_path / "Processed Data"
    raw.mkdir()
    report = raw / "Account Report.xlsx"
    lunchtab = raw / "Lunchtab Users.csv"
    write_odin(
        report,
        [
            ["Student Debit", "001", 10, 3.5, 6.5, "Smith, Ava"],
            ["Faculty Debit", "999", 2, 0, 2, "Missing, Person"],
            ["Faculty Debit", "002", 2, 0, 2, "Wrong, Person"],
        ],
    )
    write_lunchtab(
        lunchtab,
        [
            user("001", "Smith", "Ava"),
            user("002", "Jones", "Bob"),
        ],
    )

    summary = run_workflow(raw_data_dir=raw, output_dir=output)

    assert summary.extracted == 3
    assert summary.matched_by_id == 1
    assert summary.exceptions == 2
    assert summary.manual_review_exceptions == 1
    assert summary.output_paths.transfer == output / FINAL_OUTPUT_NAME
    assert (output / "cleaned - Account Report.csv").is_file()
    assert (output / "processed - Account Report.csv").is_file()
    with (output / FINAL_OUTPUT_NAME).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        assert reader.fieldnames == [
            "FirstName",
            "PreferredName",
            "Surname",
            "LoginBarcode",
            "DefaultFamilyCode",
            "DefaultFamilyBalanceAmount",
            "OdinBalanceAmount",
            "ExtraColumn",
        ]
    assert len(rows) == 2
    assert (output / FINAL_OUTPUT_NAME).read_bytes().startswith(b"\xef\xbb\xbf")
    assert rows[0]["OdinBalanceAmount"] == "6.5"
    assert rows[1]["OdinBalanceAmount"] == ""
    with (output / EXCEPTIONS_OUTPUT_NAME).open(encoding="utf-8-sig", newline="") as file:
        exceptions = list(csv.DictReader(file))
    assert [row["Reason"] for row in exceptions] == [
        "no Lunchtab match",
        "barcode matched but name validation failed",
    ]
    with (output / MANUAL_REVIEW_EXCEPTIONS_OUTPUT_NAME).open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        manual_review_exceptions = list(csv.DictReader(file))
    assert [row["Reason"] for row in manual_review_exceptions] == [
        "barcode matched but name validation failed"
    ]

    with pytest.raises(FileExistsError):
        run_workflow(raw_data_dir=raw, output_dir=output)
