from __future__ import annotations

from pathlib import Path

import pytest

from odin_lunchtab.desktop import friendly_error, open_path
from odin_lunchtab.gui_controller import AppController, AppPhase
from odin_lunchtab.managed import InputInspection, ManagedRunResult
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
