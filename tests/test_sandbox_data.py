from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from odin_lunchtab.sandbox_controller import SandboxController, SandboxPhase
from odin_lunchtab.sandbox_data import (
    IdentifierConvention,
    INITIAL_BALANCE_HEADERS,
    LUNCHTAB_HEADERS,
    SandboxConfig,
    SandboxExceptionCounts,
    SandboxVerificationResult,
    generate_and_verify_sandbox_pack,
    generate_sandbox_pack,
    preset_config,
    verify_sandbox_pack,
)
from odin_lunchtab.workflow import ODIN_HEADERS, extract_odin_report


def fixed_now() -> datetime:
    return datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)


def csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def test_clean_baseline_generates_deterministic_contract_files(tmp_path: Path) -> None:
    config = preset_config("Clean baseline", output_root=tmp_path)

    first = generate_sandbox_pack(config, now=fixed_now)
    second = generate_sandbox_pack(config, now=fixed_now)

    assert first.run_dir.name == "2026-06-26_120000"
    assert second.run_dir.name == "2026-06-26_120000_2"
    assert first.paths.lunchtab_users.read_bytes() == second.paths.lunchtab_users.read_bytes()
    assert first.paths.initial_balances.read_bytes() == second.paths.initial_balances.read_bytes()

    records, malformed = extract_odin_report(first.paths.odin_workbook)
    assert malformed == []
    assert tuple(records[0].cleaned_row()) == ODIN_HEADERS
    headers, users = csv_rows(first.paths.lunchtab_users)
    assert headers == LUNCHTAB_HEADERS
    assert len(users) == config.total_lunchtab_rows
    headers, initial_rows = csv_rows(first.paths.initial_balances)
    assert headers == INITIAL_BALANCE_HEADERS
    assert len(initial_rows) == len({row["DefaultFamilyCode"] for row in users})
    assert first.expected.matched_rows == config.matchable_rows
    assert first.expected.reconciliation_exceptions == 0
    assert not first.expected.initial_balances_blocked


def test_lunchtab_only_remainder_does_not_create_matches(tmp_path: Path) -> None:
    config = replace(
        preset_config("Clean baseline", output_root=tmp_path),
        total_odin_rows=3,
        matchable_rows=3,
        total_lunchtab_rows=9,
    )

    pack = generate_sandbox_pack(config, now=fixed_now)

    assert pack.expected.odin_rows == 3
    assert pack.expected.lunchtab_rows == 9
    assert pack.expected.matched_rows == 3
    assert pack.expected.reconciliation_exceptions == 0


def test_lunchtab_barcode_and_family_code_conventions_are_independent(
    tmp_path: Path,
) -> None:
    config = replace(
        preset_config("Clean baseline", output_root=tmp_path),
        total_odin_rows=2,
        total_lunchtab_rows=2,
        matchable_rows=2,
        odin_id=IdentifierConvention(prefix="ODN-", start=100, zero_pad=4),
        lunchtab_barcode=IdentifierConvention(prefix="LT-", start=8000, zero_pad=6),
        family_code=IdentifierConvention(prefix="F-", start=900000, zero_pad=8),
    )

    pack = generate_sandbox_pack(config, now=fixed_now)
    _, users = csv_rows(pack.paths.lunchtab_users)
    _, initial_rows = csv_rows(pack.paths.initial_balances)

    assert [row["LoginBarcode"] for row in users] == ["LT-008000", "LT-008001"]
    assert [row["DefaultFamilyCode"] for row in users] == ["F-00900000", "F-00900001"]
    assert [row["FamilyCode"] for row in initial_rows] == ["F-00900000", "F-00900001"]
    assert pack.expected.matched_rows == 2
    assert pack.expected.reconciliation_exceptions == 0


def test_reconciliation_preset_covers_expected_exception_reasons(tmp_path: Path) -> None:
    pack = generate_sandbox_pack(
        preset_config("Reconciliation exceptions", output_root=tmp_path),
        now=fixed_now,
    )

    assert pack.expected.exception_reasons == {
        "ambiguous name match": 1,
        "barcode matched but name validation failed": 2,
        "duplicate Lunchtab LoginBarcode": 1,
        "duplicate Odin ID Number": 2,
        "multiple Odin records matched one Lunchtab user": 2,
        "no Lunchtab match": 2,
    }
    assert pack.expected.manual_review_exceptions == 8


def test_malformed_preset_reports_malformed_rows(tmp_path: Path) -> None:
    pack = generate_sandbox_pack(
        preset_config("Malformed source rows", output_root=tmp_path),
        now=fixed_now,
    )

    assert pack.expected.malformed_odin_rows == 5
    assert pack.expected.exception_reasons == {
        "invalid monetary value": 2,
        "missing one or more required Odin fields": 3,
    }


def test_initial_balances_blocker_preset_verifies_as_blocked(tmp_path: Path) -> None:
    result = generate_and_verify_sandbox_pack(
        preset_config("InitialBalances blockers", output_root=tmp_path),
        now=fixed_now,
    )

    assert result.verification is not None
    assert result.pack.expected.initial_balances_blocked
    assert result.verification.initial_balances_blocked
    assert result.verification.mismatches == ()
    assert result.verification.initial_balances_passed


def test_clean_baseline_round_trips_through_production_workflows(tmp_path: Path) -> None:
    pack = generate_sandbox_pack(
        preset_config("Clean baseline", output_root=tmp_path), now=fixed_now
    )

    verification = verify_sandbox_pack(pack)

    assert verification.mismatches == ()
    assert verification.reconciliation_passed
    assert verification.initial_balances_passed


def test_manifest_uses_filenames_and_expected_counts_without_absolute_inputs(
    tmp_path: Path,
) -> None:
    pack = generate_sandbox_pack(
        preset_config("Clean baseline", output_root=tmp_path), now=fixed_now
    )

    manifest = json.loads(pack.paths.manifest.read_text(encoding="utf-8"))

    assert manifest["generated_files"] == {
        "initial_balances": "Sandbox InitialBalances.csv",
        "lunchtab_users": "Sandbox Lunchtab Users.csv",
        "odin_workbook": "Sandbox Odin Account Balance Report.xlsx",
    }
    assert manifest["expected"]["matched_rows"] == 20
    assert str(tmp_path) not in pack.paths.manifest.read_text(encoding="utf-8")


def test_controller_blocks_invalid_config_and_resets_after_result(tmp_path: Path) -> None:
    controller = SandboxController(preset_config("Clean baseline", output_root=tmp_path))
    invalid = replace(controller.state.config, matchable_rows=999)

    try:
        controller.update_config(invalid)
    except ValueError as error:
        controller.failed(str(error))

    assert controller.state.phase == SandboxPhase.ERROR
    controller.update_config(preset_config("Clean baseline", output_root=tmp_path))
    state = controller.begin_generation(verify=True)
    assert state.phase == SandboxPhase.GENERATING
    assert not state.can_generate

    pack = generate_sandbox_pack(controller.state.config, now=fixed_now)
    result = SandboxVerificationResult(pack=pack)
    state = controller.generation_succeeded(result)

    assert state.phase == SandboxPhase.COMPLETE
    assert state.can_generate
    assert state.output_folder == pack.run_dir


def test_custom_exception_counts_round_trip(tmp_path: Path) -> None:
    config = replace(
        SandboxConfig(
            output_root=tmp_path, total_odin_rows=5, total_lunchtab_rows=5, matchable_rows=2
        ),
        exceptions=SandboxExceptionCounts(unmatched_odin=1, malformed_invalid_balances=2),
    )

    pack = generate_sandbox_pack(config, now=fixed_now)

    assert pack.expected.valid_odin_rows == 3
    assert pack.expected.malformed_odin_rows == 2
    assert pack.expected.exception_reasons == {
        "invalid monetary value": 2,
        "no Lunchtab match": 1,
    }
