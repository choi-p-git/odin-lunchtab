from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from odin_lunchtab.managed import preview_profile
from odin_lunchtab.profiles import (
    LEGACY_DEFAULT_PROFILE,
    CrosswalkEntry,
    MatchingProfile,
    MatchingRule,
    TransformStep,
)
from odin_lunchtab.workflow import OdinRecord, match_balances_detailed, run_workflow


def record(account_type: str, identifier: str, name: str, balance: str = "5") -> OdinRecord:
    surname, first_name = (part.strip() for part in name.split(",", 1))
    return OdinRecord(
        account_type,
        identifier,
        "5",
        "0",
        balance,
        name,
        surname,
        first_name,
    )


def user(
    barcode: str,
    surname: str,
    first_name: str,
    *,
    external_id: str = "",
    email: str = "",
) -> dict[str, str]:
    return {
        "FirstName": first_name,
        "PreferredName": "",
        "Surname": surname,
        "LoginBarcode": barcode,
        "ExternalId": external_id,
        "EmailAddress": email,
        "DefaultFamilyBalanceAmount": "0",
    }


def test_custom_rule_supports_arbitrary_mixed_identifier_and_external_id() -> None:
    profile = MatchingProfile(
        name="Venue",
        rules=(
            MatchingRule(
                "Faculty employee key",
                target_field="ExternalId",
                account_types=("Faculty Wallet",),
                transforms=(
                    TransformStep("strip_leading_zeros"),
                    TransformStep("add_prefix", "EMP-"),
                    TransformStep("add_suffix", "-ACTIVE"),
                ),
            ),
        ),
    )
    users = [user("unrelated", "Smith", "Ava", external_id="EMP-A12B-ACTIVE")]

    result = match_balances_detailed(
        [record("Faculty Wallet", "A12B", "Smith, Ava")],
        users,
        profile=profile,
    )

    assert result.output_users[0]["OdinBalanceAmount"] == "5"
    assert result.counts["rule:Faculty employee key"] == 1
    assert result.decisions[0].transformed_value == "EMP-A12B-ACTIVE"


def test_rule_scope_and_disabled_rules_are_respected() -> None:
    profile = MatchingProfile(
        name="Venue",
        rules=(
            MatchingRule(
                "Disabled",
                transforms=(TransformStep("add_prefix", "X"),),
                enabled=False,
            ),
            MatchingRule("Faculty only", account_types=("Faculty",)),
        ),
    )

    result = match_balances_detailed(
        [record("Student", "42", "Smith, Ava")],
        [user("42", "Smith", "Ava")],
        profile=profile,
    )

    assert not result.decisions
    assert result.exceptions[0]["Reason"] == "no configured identifier match"


def test_multiple_rules_to_same_user_are_safe_but_different_users_conflict() -> None:
    same_target = MatchingProfile(
        name="Same",
        rules=(
            MatchingRule("Barcode", "LoginBarcode"),
            MatchingRule("External", "ExternalId"),
        ),
    )
    users = [user("42", "Smith", "Ava", external_id="42")]
    accepted = match_balances_detailed(
        [record("Any", "42", "Smith, Ava")], users, profile=same_target
    )
    assert len(accepted.decisions) == 1
    assert accepted.decisions[0].rule_name == "Barcode + External"

    conflicting = [
        user("42", "Smith", "Ava", external_id="other"),
        user("other", "Smith", "Ava", external_id="42"),
    ]
    rejected = match_balances_detailed(
        [record("Any", "42", "Smith, Ava")], conflicting, profile=same_target
    )
    assert not rejected.decisions
    assert rejected.exceptions[0]["Reason"] == (
        "matching rules resolved to different Lunchtab users"
    )


def test_crosswalk_has_precedence_and_does_not_fall_through_when_stale() -> None:
    profile = MatchingProfile(
        name="Venue",
        rules=(MatchingRule("Exact"),),
        crosswalk=(CrosswalkEntry("Faculty", "42", "LoginBarcode", "STAFF-42"),),
        name_fallback_all=True,
    )
    accepted = match_balances_detailed(
        [record("Faculty", "42", "Smith, Ava")],
        [
            user("42", "Smith", "Ava"),
            user("STAFF-42", "Smith", "Ava"),
        ],
        profile=profile,
    )
    assert accepted.decisions[0].target_index == 1
    assert accepted.decisions[0].method == "crosswalk"

    stale = match_balances_detailed(
        [record("Faculty", "42", "Smith, Ava")],
        [user("42", "Smith", "Ava")],
        profile=profile,
    )
    assert not stale.decisions
    assert stale.exceptions[0]["Reason"] == "stale crosswalk target"


def test_name_validation_is_mandatory_for_rules_and_crosswalks() -> None:
    profile = MatchingProfile(name="Venue", rules=(MatchingRule("Exact"),))
    result = match_balances_detailed(
        [record("Any", "42", "Wrong, Person")],
        [user("42", "Smith", "Ava")],
        profile=profile,
    )
    assert not result.decisions
    assert result.exceptions[0]["Reason"] == "identifier matched but name validation failed"


def test_name_fallback_can_be_enabled_by_account_type() -> None:
    profile = MatchingProfile(
        name="Venue",
        name_fallback_account_types=("Faculty",),
    )
    users = [user("different", "Smith", "Ava")]

    faculty = match_balances_detailed(
        [record("Faculty", "42", "Smith, Ava")], users, profile=profile
    )
    student = match_balances_detailed(
        [record("Student", "42", "Smith, Ava")], users, profile=profile
    )

    assert faculty.decisions[0].method == "name"
    assert not student.decisions


def test_duplicate_odin_identity_is_scoped_by_account_type() -> None:
    profile = MatchingProfile(name="Venue", rules=(MatchingRule("Exact"),))
    result = match_balances_detailed(
        [
            record("Students", "42", "Smith, Ava"),
            record("Faculty", "42", "Jones, Bob"),
        ],
        [
            user("42", "Smith", "Ava"),
            user("42", "Jones", "Bob"),
        ],
        profile=profile,
    )
    assert all(row["Reason"] != "duplicate Odin ID Number" for row in result.exceptions)


def write_sources(tmp_path: Path) -> tuple[Path, Path]:
    odin = tmp_path / "report.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Account Type", "ID Number", "Deposits", "Spendings", "Balance", "Student"])
    sheet.append(["Faculty", "42", 5, 0, 5, "Smith, Ava"])
    sheet.append(["", "Patron Count:", 1])
    workbook.save(odin)
    lunchtab = tmp_path / "users.csv"
    with lunchtab.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "FirstName",
                "PreferredName",
                "Surname",
                "LoginBarcode",
                "ExternalId",
                "EmailAddress",
                "DefaultFamilyBalanceAmount",
            ],
        )
        writer.writeheader()
        writer.writerow(user("STAFF-42", "Smith", "Ava", external_id="EMP-42"))
    return odin, lunchtab


def test_preview_is_non_writing_and_compares_with_legacy(tmp_path: Path) -> None:
    odin, lunchtab = write_sources(tmp_path)
    profile = MatchingProfile(
        name="Venue",
        rules=(
            MatchingRule(
                "Staff prefix",
                transforms=(TransformStep("add_prefix", "STAFF-"),),
            ),
        ),
    )

    preview = preview_profile(odin, lunchtab, profile)

    assert preview.matched == 1
    assert preview.changed_from_legacy == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report.xlsx", "users.csv"]


def test_workflow_writes_match_audit_without_changing_transfer_schema(
    tmp_path: Path,
) -> None:
    odin, lunchtab = write_sources(tmp_path)
    output = tmp_path / "output"
    profile = MatchingProfile(
        name="Venue",
        rules=(
            MatchingRule(
                "Staff prefix",
                transforms=(TransformStep("add_prefix", "STAFF-"),),
            ),
        ),
    )

    summary = run_workflow(
        raw_data_dir=tmp_path,
        output_dir=output,
        odin_path=odin,
        lunchtab_path=lunchtab,
        profile=profile,
    )

    with summary.output_paths.match_audit.open(encoding="utf-8-sig") as file:
        audit = list(csv.DictReader(file))
    with summary.output_paths.transfer.open(encoding="utf-8-sig") as file:
        transfer_reader = csv.DictReader(file)
        list(transfer_reader)
    assert audit[0]["Rule"] == "Staff prefix"
    assert audit[0]["Profile"] == "Venue"
    assert "Match Method" not in transfer_reader.fieldnames


def test_legacy_default_retains_existing_summary_methods() -> None:
    result = match_balances_detailed(
        [record("Any", "42", "Smith, Ava")],
        [user("42", "Smith", "Ava")],
        profile=LEGACY_DEFAULT_PROFILE,
    )
    assert result.counts == {"id": 1}


def test_email_username_matching_is_case_insensitive_and_preserves_plus_tag() -> None:
    profile = MatchingProfile(
        name="Email Venue",
        rules=(
            MatchingRule(
                "Email username",
                target_field="EmailUsername",
                transforms=(TransformStep("add_suffix", "+Lunch"),),
            ),
        ),
    )
    result = match_balances_detailed(
        [record("Staff", "A.User", "Smith, Ava")],
        [user("different", "Smith", "Ava", email="a.user+lunch@Example.ORG")],
        profile=profile,
    )

    assert len(result.decisions) == 1
    assert result.decisions[0].target_field == "EmailUsername"
    assert result.decisions[0].transformed_value == "A.User+Lunch"


def test_email_domain_filter_is_exact_and_case_insensitive() -> None:
    profile = MatchingProfile(
        name="Email Venue",
        rules=(
            MatchingRule(
                "Approved email",
                target_field="EmailUsername",
                allowed_email_domains=("SCHOOL.ORG",),
            ),
        ),
    )
    accepted = match_balances_detailed(
        [record("Staff", "ava", "Smith, Ava")],
        [user("different", "Smith", "Ava", email="AVA@school.org")],
        profile=profile,
    )
    rejected = match_balances_detailed(
        [record("Staff", "ava", "Smith, Ava")],
        [user("different", "Smith", "Ava", email="ava@sub.school.org")],
        profile=profile,
    )

    assert accepted.decisions
    assert not rejected.decisions


def test_malformed_and_duplicate_email_usernames_are_not_accepted() -> None:
    profile = MatchingProfile(
        name="Email Venue",
        rules=(MatchingRule("Email", target_field="EmailUsername"),),
    )
    malformed = match_balances_detailed(
        [record("Staff", "ava", "Smith, Ava")],
        [user("x", "Smith", "Ava", email="not-an-email")],
        profile=profile,
    )
    duplicate = match_balances_detailed(
        [record("Staff", "ava", "Smith, Ava")],
        [
            user("x", "Smith", "Ava", email="ava@one.org"),
            user("y", "Smith", "Ava", email="AVA@two.org"),
        ],
        profile=profile,
    )

    assert malformed.exceptions[0]["Reason"] == "no configured identifier match"
    assert duplicate.exceptions[0]["Reason"] == "duplicate Lunchtab identifier"


def test_email_matching_still_requires_name_validation() -> None:
    profile = MatchingProfile(
        name="Email Venue",
        rules=(MatchingRule("Email", target_field="EmailUsername"),),
    )
    result = match_balances_detailed(
        [record("Staff", "ava", "Wrong, Person")],
        [user("x", "Smith", "Ava", email="ava@school.org")],
        profile=profile,
    )

    assert not result.decisions
    assert result.exceptions[0]["Reason"] == "identifier matched but name validation failed"


def test_non_email_identifiers_remain_case_sensitive() -> None:
    profile = MatchingProfile(name="Venue", rules=(MatchingRule("Exact"),))
    result = match_balances_detailed(
        [record("Staff", "ABC", "Smith, Ava")],
        [user("abc", "Smith", "Ava")],
        profile=profile,
    )

    assert not result.decisions
