from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from odin_lunchtab.managed import InputInspection, ManagedRunResult
from odin_lunchtab.initial_balances import (
    InitialBalancesInspection,
    InitialBalancesRunResult,
)
from odin_lunchtab.profiles import LEGACY_DEFAULT_PROFILE, MatchingProfile


class AppPhase(Enum):
    EMPTY = "empty"
    READY_TO_VALIDATE = "ready_to_validate"
    VALIDATING = "validating"
    VALID = "valid"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class AppState:
    odin_path: Path | None = None
    lunchtab_path: Path | None = None
    output_root: Path | None = None
    phase: AppPhase = AppPhase.EMPTY
    inspection: InputInspection | None = None
    result: ManagedRunResult | None = None
    profile: MatchingProfile = LEGACY_DEFAULT_PROFILE
    message: str = "Select the two source files to begin."

    @property
    def can_validate(self) -> bool:
        return (
            self.odin_path is not None
            and self.lunchtab_path is not None
            and self.phase not in {AppPhase.VALIDATING, AppPhase.PROCESSING}
        )

    @property
    def can_process(self) -> bool:
        return self.phase == AppPhase.VALID


class AppController:
    def __init__(self, output_root: Path) -> None:
        self.state = AppState(output_root=output_root)

    def select_odin(self, path: Path) -> AppState:
        return self._change_input(odin_path=path)

    def select_lunchtab(self, path: Path) -> AppState:
        return self._change_input(lunchtab_path=path)

    def select_output_root(self, path: Path) -> AppState:
        self.state = replace(self.state, output_root=path)
        return self.state

    def select_profile(self, profile: MatchingProfile) -> AppState:
        profile.validate()
        phase = (
            AppPhase.READY_TO_VALIDATE
            if self.state.odin_path is not None and self.state.lunchtab_path is not None
            else AppPhase.EMPTY
        )
        self.state = replace(
            self.state,
            profile=profile,
            phase=phase,
            inspection=None,
            result=None,
            message=f"Profile changed to {profile.name}. Validate the selected files.",
        )
        return self.state

    def begin_validation(self) -> AppState:
        if not self.state.can_validate:
            raise RuntimeError("Both input files must be selected before validation.")
        self.state = replace(
            self.state,
            phase=AppPhase.VALIDATING,
            inspection=None,
            result=None,
            message="Validating source files…",
        )
        return self.state

    def validation_succeeded(self, inspection: InputInspection) -> AppState:
        self.state = replace(
            self.state,
            phase=AppPhase.VALID,
            inspection=inspection,
            message="Files are valid and ready to process.",
        )
        return self.state

    def begin_processing(self) -> AppState:
        if not self.state.can_process:
            raise RuntimeError("Validate the selected files before processing.")
        self.state = replace(
            self.state,
            phase=AppPhase.PROCESSING,
            result=None,
            message="Processing balances and writing reports…",
        )
        return self.state

    def processing_succeeded(self, result: ManagedRunResult) -> AppState:
        self.state = replace(
            self.state,
            phase=AppPhase.COMPLETE,
            result=result,
            message="Transfer complete.",
        )
        return self.state

    def failed(self, message: str) -> AppState:
        self.state = replace(self.state, phase=AppPhase.ERROR, message=message)
        return self.state

    def _change_input(
        self,
        *,
        odin_path: Path | None = None,
        lunchtab_path: Path | None = None,
    ) -> AppState:
        values = {
            "odin_path": odin_path if odin_path is not None else self.state.odin_path,
            "lunchtab_path": (
                lunchtab_path if lunchtab_path is not None else self.state.lunchtab_path
            ),
            "inspection": None,
            "result": None,
        }
        both_selected = values["odin_path"] is not None and values["lunchtab_path"] is not None
        values["phase"] = AppPhase.READY_TO_VALIDATE if both_selected else AppPhase.EMPTY
        values["message"] = (
            "Validate the selected files."
            if both_selected
            else "Select the two source files to begin."
        )
        self.state = replace(self.state, **values)
        return self.state


class InitialBalancesPhase(Enum):
    EMPTY = "empty"
    READY_TO_VALIDATE = "ready_to_validate"
    VALIDATING = "validating"
    VALID = "valid"
    PROCESSING = "processing"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class InitialBalancesState:
    transfer_path: Path | None = None
    initial_balances_path: Path | None = None
    output_root: Path | None = None
    phase: InitialBalancesPhase = InitialBalancesPhase.EMPTY
    inspection: InitialBalancesInspection | None = None
    result: InitialBalancesRunResult | None = None
    message: str = "Select the reconciled transfer and InitialBalances CSV files."

    @property
    def can_validate(self) -> bool:
        return (
            self.transfer_path is not None
            and self.initial_balances_path is not None
            and self.phase not in {InitialBalancesPhase.VALIDATING, InitialBalancesPhase.PROCESSING}
        )

    @property
    def can_process(self) -> bool:
        return self.phase == InitialBalancesPhase.VALID


class InitialBalancesController:
    def __init__(self, output_root: Path) -> None:
        self.state = InitialBalancesState(output_root=output_root)

    def select_transfer(self, path: Path) -> InitialBalancesState:
        return self._change_input(transfer_path=path)

    def select_initial_balances(self, path: Path) -> InitialBalancesState:
        return self._change_input(initial_balances_path=path)

    def select_output_root(self, path: Path) -> InitialBalancesState:
        self.state = replace(self.state, output_root=path)
        return self.state

    def begin_validation(self) -> InitialBalancesState:
        if not self.state.can_validate:
            raise RuntimeError("Both CSV files must be selected before validation.")
        self.state = replace(
            self.state,
            phase=InitialBalancesPhase.VALIDATING,
            inspection=None,
            result=None,
            message="Validating InitialBalances inputs…",
        )
        return self.state

    def validation_succeeded(self, inspection: InitialBalancesInspection) -> InitialBalancesState:
        self.state = replace(
            self.state,
            phase=InitialBalancesPhase.VALID,
            inspection=inspection,
            message="Files are valid and ready to transfer.",
        )
        return self.state

    def begin_processing(self) -> InitialBalancesState:
        if not self.state.can_process:
            raise RuntimeError("Validate the selected files before processing.")
        self.state = replace(
            self.state,
            phase=InitialBalancesPhase.PROCESSING,
            result=None,
            message="Aggregating, transferring, and auditing balances…",
        )
        return self.state

    def processing_succeeded(self, result: InitialBalancesRunResult) -> InitialBalancesState:
        phase = (
            InitialBalancesPhase.BLOCKED
            if result.summary.blocked
            else InitialBalancesPhase.COMPLETE
        )
        message = (
            "Import blocked. Resolve the reported exceptions and run again."
            if result.summary.blocked
            else "InitialBalances transfer and audit complete."
        )
        self.state = replace(self.state, phase=phase, result=result, message=message)
        return self.state

    def failed(self, message: str) -> InitialBalancesState:
        self.state = replace(self.state, phase=InitialBalancesPhase.ERROR, message=message)
        return self.state

    def _change_input(
        self,
        *,
        transfer_path: Path | None = None,
        initial_balances_path: Path | None = None,
    ) -> InitialBalancesState:
        values = {
            "transfer_path": (
                transfer_path if transfer_path is not None else self.state.transfer_path
            ),
            "initial_balances_path": (
                initial_balances_path
                if initial_balances_path is not None
                else self.state.initial_balances_path
            ),
            "inspection": None,
            "result": None,
        }
        both_selected = (
            values["transfer_path"] is not None and values["initial_balances_path"] is not None
        )
        values["phase"] = (
            InitialBalancesPhase.READY_TO_VALIDATE if both_selected else InitialBalancesPhase.EMPTY
        )
        values["message"] = (
            "Validate the selected files."
            if both_selected
            else "Select the reconciled transfer and InitialBalances CSV files."
        )
        self.state = replace(self.state, **values)
        return self.state
