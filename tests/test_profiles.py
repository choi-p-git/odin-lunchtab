from __future__ import annotations

import json
from pathlib import Path

import pytest

from odin_lunchtab.profiles import (
    LEGACY_DEFAULT_PROFILE,
    CrosswalkEntry,
    MatchingProfile,
    MatchingRule,
    TransformStep,
    delete_profile,
    duplicate_profile,
    export_crosswalk,
    import_crosswalk,
    import_profile,
    list_profiles,
    load_profile,
    save_profile,
    parse_email_address,
)


@pytest.mark.parametrize(
    ("steps", "source", "expected"),
    [
        ((TransformStep("trim"),), " 001 ", "001"),
        ((TransformStep("add_prefix", "STAFF-"),), "42", "STAFF-42"),
        ((TransformStep("remove_prefix", "EMP"),), "EMP42", "42"),
        ((TransformStep("add_suffix", "-A"),), "42", "42-A"),
        ((TransformStep("remove_suffix", "-A"),), "42-A", "42"),
        ((TransformStep("zero_pad", "7"),), "42", "0000042"),
        ((TransformStep("strip_leading_zeros"),), "00042", "42"),
        ((TransformStep("substring", start=2, end=6),), "AA1234ZZ", "1234"),
        (
            (
                TransformStep("trim"),
                TransformStep("strip_leading_zeros"),
                TransformStep("add_prefix", "EMP-"),
            ),
            " 00042 ",
            "EMP-42",
        ),
    ],
)
def test_transform_pipeline_preserves_string_semantics(
    steps: tuple[TransformStep, ...],
    source: str,
    expected: str,
) -> None:
    rule = MatchingRule("example", transforms=steps)

    assert rule.transform(source) == expected


def test_profile_validation_rejects_duplicate_rules_and_crosswalk_sources() -> None:
    with pytest.raises(ValueError, match="Duplicate rule"):
        MatchingProfile(
            name="Bad",
            rules=(MatchingRule("Same"), MatchingRule("same")),
        ).validate()

    with pytest.raises(ValueError, match="Duplicate crosswalk"):
        MatchingProfile(
            name="Bad",
            crosswalk=(
                CrosswalkEntry("Faculty", "42", "LoginBarcode", "A"),
                CrosswalkEntry("Faculty", "42", "ExternalId", "B"),
            ),
        ).validate()


def test_profile_storage_import_export_and_deletion(tmp_path: Path) -> None:
    profile = duplicate_profile(LEGACY_DEFAULT_PROFILE, "Venue Alpha")
    saved = save_profile(profile, tmp_path)

    loaded = load_profile(saved)
    assert loaded == profile
    assert [item.name for item in list_profiles(tmp_path)] == [
        "Legacy Default",
        "Venue Alpha",
    ]

    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    exported = export_dir / "exported.json"
    exported.write_text(saved.read_text(encoding="utf-8"), encoding="utf-8")
    imported = import_profile(exported)
    assert imported.name == profile.name
    assert imported.profile_id != profile.profile_id
    assert not imported.read_only

    delete_profile(profile, tmp_path)
    assert list_profiles(tmp_path) == [LEGACY_DEFAULT_PROFILE]


def test_profile_import_rejects_unsupported_schema(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps({"schema_version": 99, "name": "Future"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported profile schema"):
        load_profile(path)


def test_crosswalk_csv_round_trip(tmp_path: Path) -> None:
    profile = MatchingProfile(
        name="Venue",
        crosswalk=(CrosswalkEntry("Faculty Debit", "00042", "ExternalId", "employee-42"),),
    )
    path = tmp_path / "crosswalk.csv"

    export_crosswalk(profile, path)

    assert import_crosswalk(path) == profile.crosswalk


def test_legacy_profile_is_protected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be modified"):
        save_profile(LEGACY_DEFAULT_PROFILE, tmp_path)
    with pytest.raises(ValueError, match="cannot be deleted"):
        delete_profile(LEGACY_DEFAULT_PROFILE, tmp_path)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (" User.Name+tag@Example.ORG ", ("User.Name+tag", "example.org")),
        ("plain@example.org", ("plain", "example.org")),
        ("", None),
        ("missing-at.example.org", None),
        ("two@@example.org", None),
        ("@example.org", None),
        ("user@", None),
        ("user@bad..example", None),
    ],
)
def test_email_parser_extracts_complete_username_safely(
    address: str,
    expected: tuple[str, str] | None,
) -> None:
    assert parse_email_address(address) == expected


def test_schema_one_profile_migrates_to_schema_two(tmp_path: Path) -> None:
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Old Venue",
                "rules": [{"name": "Exact"}],
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile(path)

    assert profile.schema_version == 2
    assert profile.rules[0].allowed_email_domains == ()
