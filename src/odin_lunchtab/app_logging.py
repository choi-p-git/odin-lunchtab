from __future__ import annotations

import logging
import os
from pathlib import Path

LOGGER_NAME = "odin_lunchtab"


def log_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Odin Lunchtab" / "logs"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(directory / "application.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
