from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from openpyxl import Workbook

from odin_lunchtab import managed
from odin_lunchtab.managed import choose_run_dir, inspect_inputs, run_managed_workflow
from odin_lunchtab.profiles import MatchingProfile, MatchingRule


def write_odin(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Account Balance Report"])
    sheet.append(["Account Type", "ID Number", "Deposits", "Spendings", "Balance", "Student"])
    for row in rows:
        sheet.append(row)
    sheet.append(["", "Patron Count:", len(rows)])
    workbook.save(path)


def write_lunchtab(path: Path, *, include_balance: bool = True) -> None:
    headers = ["FirstName", "PreferredName", "Surname", "LoginBarcode"]
    if include_balance:
        headers.append("DefaultFamilyBalanceAmount")
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerow(
            {
                "FirstName": "Ava",
                "PreferredName": "",
                "Surname": "Smith",
                "LoginBarcode": "001",
                **({"DefaultFamilyBalanceAmount": "0"} if include_balance else {}),
            }
        )


def source_files(tmp_path: Path) -> tuple[Path, Path]:
    odin = tmp_path / "Private Student Report.xlsx"
    lunchtab = tmp_path / "Lunchtab Users.csv"
    write_odin(odin, [["Student Debit", "001", 10, 3, 7, "Smith, Ava"]])
    write_lunchtab(lunchtab)
    return odin, lunchtab


def test_inspect_inputs_reports_counts(tmp_path: Path) -> None:
    odin, lunchtab = source_files(tmp_path)

    inspection = inspect_inputs(odin, lunchtab)

    assert inspection.odin_rows == 1
    assert inspection.malformed_odin_rows == 0
    assert inspection.lunchtab_rows == 1


@pytest.mark.parametrize(
    ("odin_name", "lunchtab_name", "message"),
    [
        ("report.xls", "users.csv", "must be an .xlsx"),
        ("report.xlsx", "users.txt", "must be a .csv"),
    ],
)
def test_inspect_inputs_rejects_wrong_extensions(
    tmp_path: Path,
    odin_name: str,
    lunchtab_name: str,
    message: str,
) -> None:
    odin = tmp_path / odin_name
    lunchtab = tmp_path / lunchtab_name

    with pytest.raises(ValueError, match=message):
        inspect_inputs(odin, lunchtab)


def test_inspect_inputs_rejects_missing_lunchtab_headers(tmp_path: Path) -> None:
    odin = tmp_path / "report.xlsx"
    lunchtab = tmp_path / "users.csv"
    write_odin(odin, [["Student Debit", "001", 10, 3, 7, "Smith, Ava"]])
    write_lunchtab(lunchtab, include_balance=False)

    with pytest.raises(ValueError, match="DefaultFamilyBalanceAmount"):
        inspect_inputs(odin, lunchtab)


def test_email_address_is_required_only_for_email_rules(tmp_path: Path) -> None:
    odin, lunchtab = source_files(tmp_path)
    inspect_inputs(odin, lunchtab)

    profile = MatchingProfile(
        name="Email Venue",
        rules=(MatchingRule("Email", target_field="EmailUsername"),),
    )
    with pytest.raises(ValueError, match="EmailAddress"):
        inspect_inputs(odin, lunchtab, profile)


def test_choose_run_dir_adds_suffix_for_collisions(tmp_path: Path) -> None:
    started = datetime(2026, 6, 23, 20, 15, 30, tzinfo=timezone.utc)
    (tmp_path / "2026-06-23_201530").mkdir()
    (tmp_path / "2026-06-23_201530_2").mkdir()

    assert choose_run_dir(tmp_path, started).name == "2026-06-23_201530_3"


def test_managed_run_publishes_complete_folder_and_private_manifest(tmp_path: Path) -> None:
    odin, lunchtab = source_files(tmp_path)
    output_root = tmp_path / "results"
    times = iter(
        [
            datetime(2026, 6, 23, 20, 15, 30, tzinfo=timezone.utc),
            datetime(2026, 6, 23, 20, 15, 31, tzinfo=timezone.utc),
        ]
    )

    result = run_managed_workflow(
        odin_path=odin,
        lunchtab_path=lunchtab,
        output_root=output_root,
        now=lambda: next(times),
    )

    assert result.run_dir.name == "2026-06-23_201530"
    assert result.summary.output_paths.transfer.is_file()
    assert result.manifest_path.is_file()
    assert not list(output_root.glob(".staging-*"))
    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["inputs"] == {
        "odin": "Private Student Report.xlsx",
        "lunchtab": "Lunchtab Users.csv",
    }
    assert str(tmp_path) not in manifest_text
    assert "Smith" not in manifest_text
    assert "7" not in json.dumps(manifest["inputs"])
    assert manifest["counts"]["matched_by_id"] == 1
    assert manifest["matching_profile"]["name"] == "Legacy Default"
    assert "Exact LoginBarcode" not in manifest["matching_profile"]["matches_by_rule"]


def test_managed_run_removes_staging_folder_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    odin, lunchtab = source_files(tmp_path)
    output_root = tmp_path / "results"

    def fail_workflow(**_: object) -> None:
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(managed, "run_workflow", fail_workflow)

    with pytest.raises(RuntimeError, match="simulated"):
        run_managed_workflow(
            odin_path=odin,
            lunchtab_path=lunchtab,
            output_root=output_root,
        )

    assert not list(output_root.glob(".staging-*"))
    assert not [path for path in output_root.iterdir() if path.is_dir()]
