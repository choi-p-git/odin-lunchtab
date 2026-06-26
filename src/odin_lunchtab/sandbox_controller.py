from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from odin_lunchtab.sandbox_data import SandboxConfig, SandboxVerificationResult, validate_config


class SandboxPhase(Enum):
    READY = "ready"
    GENERATING = "generating"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class SandboxState:
    config: SandboxConfig
    phase: SandboxPhase = SandboxPhase.READY
    result: SandboxVerificationResult | None = None
    message: str = "Configure sandbox data and generate a test pack."

    @property
    def can_generate(self) -> bool:
        return self.phase not in {SandboxPhase.GENERATING}

    @property
    def output_folder(self) -> Path | None:
        if self.result is None:
            return None
        return self.result.pack.run_dir


class SandboxController:
    def __init__(self, config: SandboxConfig) -> None:
        validate_config(config)
        self.state = SandboxState(config=config)

    def update_config(self, config: SandboxConfig) -> SandboxState:
        validate_config(config)
        self.state = replace(
            self.state,
            config=config,
            phase=SandboxPhase.READY,
            result=None,
            message="Configuration updated. Generate a sandbox test pack.",
        )
        return self.state

    def begin_generation(self, *, verify: bool) -> SandboxState:
        if not self.state.can_generate:
            raise RuntimeError("Sandbox generation is already running.")
        validate_config(self.state.config)
        message = (
            "Generating and verifying sandbox data..." if verify else "Generating sandbox data..."
        )
        self.state = replace(
            self.state,
            phase=SandboxPhase.GENERATING,
            result=None,
            message=message,
        )
        return self.state

    def generation_succeeded(self, result: SandboxVerificationResult) -> SandboxState:
        verification = result.verification
        if verification is None:
            message = "Sandbox data generated."
        elif verification.mismatches:
            message = "Sandbox data generated, but verification found mismatches."
        else:
            message = "Sandbox data generated and verified."
        self.state = replace(
            self.state,
            phase=SandboxPhase.COMPLETE,
            result=result,
            message=message,
        )
        return self.state

    def failed(self, message: str) -> SandboxState:
        self.state = replace(self.state, phase=SandboxPhase.ERROR, message=message)
        return self.state
