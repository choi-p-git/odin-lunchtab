from __future__ import annotations

import sys
from pathlib import Path

import pytest

from odin_lunchtab import cli
from odin_lunchtab.profiles import MatchingProfile, export_profile
from odin_lunchtab.workflow import OutputPaths, RunSummary


def test_cli_keeps_existing_arguments_and_prints_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = OutputPaths(
        cleaned=tmp_path / "cleaned.csv",
        processed=tmp_path / "processed.csv",
        transfer=tmp_path / "transfer.csv",
        exceptions=tmp_path / "exceptions.csv",
        manual_review_exceptions=tmp_path / "review.csv",
    )
    summary = RunSummary(3, 0, 2, 1, 0, 0, 3, paths)
    received: dict[str, object] = {}

    def fake_run_workflow(**kwargs: object) -> RunSummary:
        received.update(kwargs)
        return summary

    monkeypatch.setattr(cli, "run_workflow", fake_run_workflow)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "odin-lunchtab",
            "--odin",
            "odin.xlsx",
            "--lunchtab",
            "users.csv",
            "--output-dir",
            str(tmp_path),
        ],
    )

    cli.main()

    assert received["odin_path"] == Path("odin.xlsx")
    assert received["lunchtab_path"] == Path("users.csv")
    assert "Matched by ID:             2" in capsys.readouterr().out


def test_cli_loads_profile_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = tmp_path / "venue.json"
    export_profile(MatchingProfile(name="Venue"), profile_path)
    received: dict[str, object] = {}
    paths = OutputPaths(
        cleaned=tmp_path / "cleaned.csv",
        processed=tmp_path / "processed.csv",
        transfer=tmp_path / "transfer.csv",
        exceptions=tmp_path / "exceptions.csv",
        manual_review_exceptions=tmp_path / "review.csv",
    )

    def fake_run_workflow(**kwargs: object) -> RunSummary:
        received.update(kwargs)
        return RunSummary(0, 0, 0, 0, 0, 0, 0, paths)

    monkeypatch.setattr(cli, "run_workflow", fake_run_workflow)
    monkeypatch.setattr(
        sys,
        "argv",
        ["odin-lunchtab", "--profile", str(profile_path)],
    )

    cli.main()

    assert received["profile"].name == "Venue"
