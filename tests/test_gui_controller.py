from __future__ import annotations

from pathlib import Path

import pytest

from odin_lunchtab.desktop import friendly_error, open_path
from odin_lunchtab.gui_controller import AppController, AppPhase
from odin_lunchtab.gui_controller import (
    InitialBalancesController,
    InitialBalancesPhase,
    ManualReconciliationController,
    ManualReconciliationPhase,
)
from odin_lunchtab.initial_balances import (
    InitialBalancesInspection,
    InitialBalancesOutputPaths,
    InitialBalancesPreflight,
    InitialBalancesRunResult,
    InitialBalancesSummary,
)
from odin_lunchtab.managed import InputInspection, ManagedRunResult
from odin_lunchtab.manual_reconciliation import (
    ManualReconciliationOutputPaths,
    ManualReconciliationRunResult,
    ManualReconciliationSummary,
)
from odin_lunchtab.profiles import MatchingProfile
from odin_lunchtab.workflow import OutputPaths, RunSummary


def inspection(tmp_path: Path) -> InputInspection:
    return InputInspection(tmp_path / "odin.xlsx", tmp_path / "users.csv", 10, 1, 12)


def managed_result(tmp_path: Path) -> ManagedRunResult:
    paths = OutputPaths(
        cleaned=tmp_path / "cleaned.csv",
        processed=tmp_path / "processed.csv",
        transfer=tmp_path / "transfer.csv",
        exceptions=tmp_path / "exceptions.csv",
        manual_review_exceptions=tmp_path / "review.csv",
    )
    summary = RunSummary(10, 1, 7, 1, 2, 1, 12, paths)
    return ManagedRunResult(tmp_path, summary, tmp_path / "run-manifest.json")


def test_controller_requires_validation_before_processing(tmp_path: Path) -> None:
    controller = AppController(tmp_path)
    controller.select_odin(tmp_path / "odin.xlsx")
    state = controller.select_lunchtab(tmp_path / "users.csv")

    assert state.phase == AppPhase.READY_TO_VALIDATE
    assert state.can_validate
    assert not state.can_process

    controller.begin_validation()
    state = controller.validation_succeeded(inspection(tmp_path))
    assert state.phase == AppPhase.VALID
    assert state.can_process

    controller.begin_processing()
    state = controller.processing_succeeded(managed_result(tmp_path))
    assert state.phase == AppPhase.COMPLETE
    assert state.result is not None


def test_changing_an_input_invalidates_previous_results(tmp_path: Path) -> None:
    controller = AppController(tmp_path)
    controller.select_odin(tmp_path / "odin.xlsx")
    controller.select_lunchtab(tmp_path / "users.csv")
    controller.begin_validation()
    controller.validation_succeeded(inspection(tmp_path))

    state = controller.select_odin(tmp_path / "replacement.xlsx")

    assert state.phase == AppPhase.READY_TO_VALIDATE
    assert state.inspection is None
    assert state.result is None


def test_changing_profile_invalidates_previous_validation(tmp_path: Path) -> None:
    controller = AppController(tmp_path)
    controller.select_odin(tmp_path / "odin.xlsx")
    controller.select_lunchtab(tmp_path / "users.csv")
    controller.begin_validation()
    controller.validation_succeeded(inspection(tmp_path))

    state = controller.select_profile(MatchingProfile(name="Venue"))

    assert state.phase == AppPhase.READY_TO_VALIDATE
    assert state.inspection is None
    assert state.profile.name == "Venue"


def test_controller_rejects_invalid_transitions(tmp_path: Path) -> None:
    controller = AppController(tmp_path)

    with pytest.raises(RuntimeError, match="Both input files"):
        controller.begin_validation()
    with pytest.raises(RuntimeError, match="Validate"):
        controller.begin_processing()


def test_friendly_error_hides_unexpected_exception_details() -> None:
    assert friendly_error(ValueError("bad headers")) == "bad headers"
    assert "secret student" not in friendly_error(RuntimeError("secret student"))


def test_open_path_uses_windows_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.csv"
    report.touch()
    opened: list[Path] = []
    monkeypatch.setattr("odin_lunchtab.desktop.os.startfile", opened.append)

    open_path(report)

    assert opened == [report]


def initial_inspection(tmp_path: Path) -> InitialBalancesInspection:
    return InitialBalancesInspection(
        tmp_path / "transfer.csv",
        tmp_path / "InitialBalances.csv",
        5,
        3,
        10,
    )


def initial_preflight(*, blocked: bool) -> InitialBalancesPreflight:
    return InitialBalancesPreflight(
        transfer_rows=5,
        populated_balance_rows=3,
        target_rows=10,
        matched_source_rows=0 if blocked else 3,
        updated_families=0 if blocked else 2,
        exceptions=1 if blocked else 0,
        source_total="12.5",
        applied_total="0" if blocked else "12.5",
        blocked_total="12.5" if blocked else "0",
        original_matched_total="0",
        final_matched_total="0" if blocked else "12.5",
        blocked=blocked,
        exception_reasons={"DefaultFamilyCode not found in InitialBalances": 1} if blocked else {},
    )


def initial_result(tmp_path: Path, *, blocked: bool) -> InitialBalancesRunResult:
    paths = InitialBalancesOutputPaths(
        None if blocked else tmp_path / "Processed - InitialBalances.csv",
        tmp_path / "audit.csv",
        tmp_path / "exceptions.csv",
    )
    summary = InitialBalancesSummary(
        transfer_rows=5,
        populated_balance_rows=3,
        target_rows=10,
        matched_source_rows=0 if blocked else 3,
        updated_families=0 if blocked else 2,
        exceptions=1 if blocked else 0,
        source_total="12.5",
        original_matched_total="0",
        final_matched_total="0" if blocked else "12.5",
        applied_total="0" if blocked else "12.5",
        blocked=blocked,
        output_paths=paths,
    )
    return InitialBalancesRunResult(tmp_path, summary, tmp_path / "manifest.json")


def test_initial_balances_controller_tracks_complete_and_blocked_runs(
    tmp_path: Path,
) -> None:
    controller = InitialBalancesController(tmp_path)
    controller.select_transfer(tmp_path / "transfer.csv")
    state = controller.select_initial_balances(tmp_path / "InitialBalances.csv")
    assert state.phase == InitialBalancesPhase.READY_TO_VALIDATE
    assert state.can_validate

    controller.begin_validation()
    state = controller.validation_succeeded(
        initial_inspection(tmp_path),
        initial_preflight(blocked=False),
    )
    assert state.phase == InitialBalancesPhase.VALID
    assert state.can_process
    assert state.preflight is not None
    assert not state.preflight.blocked

    controller.begin_processing()
    state = controller.processing_succeeded(initial_result(tmp_path, blocked=False))
    assert state.phase == InitialBalancesPhase.COMPLETE

    controller.select_transfer(tmp_path / "reconciled.csv")
    controller.begin_validation()
    state = controller.validation_succeeded(
        initial_inspection(tmp_path),
        initial_preflight(blocked=True),
    )
    assert state.preflight is not None
    assert state.preflight.blocked
    assert "blocked" in state.message.casefold()
    controller.begin_processing()
    state = controller.processing_succeeded(initial_result(tmp_path, blocked=True))
    assert state.phase == InitialBalancesPhase.BLOCKED
    assert "blocked" in state.message.casefold()


def manual_result(tmp_path: Path, *, status: str = "PASS") -> ManualReconciliationRunResult:
    paths = ManualReconciliationOutputPaths(
        delta_audit=tmp_path / "delta.csv",
        summary=tmp_path / "summary.md",
    )
    summary = ManualReconciliationSummary(
        original_rows=5,
        edited_rows=5,
        unchanged_automated_matches=3,
        manual_resolutions=1,
        changed_automated_balances=0,
        cleared_automated_balances=0,
        invalid_manual_amounts=1 if status == "BLOCKED" else 0,
        family_code_changes=0,
        identity_field_changes=0,
        other_field_changes=0,
        status=status,
        output_paths=paths,
    )
    return ManualReconciliationRunResult(tmp_path, summary, tmp_path / "manifest.json")


def test_manual_reconciliation_controller_tracks_review_and_blocked_status(
    tmp_path: Path,
) -> None:
    controller = ManualReconciliationController(tmp_path)
    controller.select_original_transfer(tmp_path / "Original Transfer.csv")
    state = controller.select_edited_transfer(tmp_path / "Edited Transfer.csv")

    assert state.phase == ManualReconciliationPhase.READY_TO_REVIEW
    assert state.can_review

    controller.begin_review()
    state = controller.review_succeeded(manual_result(tmp_path))
    assert state.phase == ManualReconciliationPhase.COMPLETE
    assert "complete" in state.message.casefold()

    controller.select_edited_transfer(tmp_path / "Edited Transfer v2.csv")
    controller.begin_review()
    state = controller.review_succeeded(manual_result(tmp_path, status="BLOCKED"))
    assert state.phase == ManualReconciliationPhase.BLOCKED
    assert "blocked" in state.message.casefold()


def test_manual_reconciliation_controller_rejects_review_without_inputs(
    tmp_path: Path,
) -> None:
    controller = ManualReconciliationController(tmp_path)

    with pytest.raises(RuntimeError, match="Both transfer CSV"):
        controller.begin_review()
