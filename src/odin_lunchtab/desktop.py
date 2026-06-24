from __future__ import annotations

import os
from pathlib import Path


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Result no longer exists: {path}")
    os.startfile(path)  # type: ignore[attr-defined]


def friendly_error(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return str(error)
    if isinstance(error, PermissionError):
        return "Windows denied access to a selected file or output folder."
    if isinstance(error, ValueError):
        return str(error)
    return "The transfer could not be completed. See the diagnostic log for details."
