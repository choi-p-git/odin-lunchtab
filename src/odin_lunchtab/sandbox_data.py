from __future__ import annotations

import csv
import json
import random
import shutil
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Literal

from openpyxl import Workbook

from odin_lunchtab.initial_balances import (
    InitialBalancesSummary,
    run_initial_balances_workflow,
)
from odin_lunchtab.managed import choose_run_dir, default_output_root, run_managed_workflow
from odin_lunchtab.workflow import (
    FINAL_OUTPUT_NAME,
    ODIN_HEADERS,
    extract_odin_report,
    match_balances_detailed,
    read_csv,
)

SANDBOX_APP_NAME = "Odin Lunchtab Sandbox Data Generator"
LUNCHTAB_HEADERS = [
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "ExternalId",
    "EmailAddress",
    "DefaultFamilyCode",
    "DefaultFamilyBalanceAmount",
]
INITIAL_BALANCE_HEADERS = ["FamilyName", "FamilyCode", "Amount"]
PRESET_NAMES = (
    "Clean baseline",
    "Reconciliation exceptions",
    "Malformed source rows",
    "InitialBalances blockers",
    "Mixed stress",
)
FamilyGrouping = Literal["one_per_family", "shared_every_n", "mixed"]
BalanceMode = Literal["positive", "positive_negative_zero"]


@dataclass(frozen=True)
class IdentifierConvention:
    prefix: str = ""
    suffix: str = ""
    start: int = 1000
    zero_pad: int = 4

    def value(self, offset: int) -> str:
        number = str(self.start + offset)
        if self.zero_pad:
            number = number.zfill(self.zero_pad)
        return f"{self.prefix}{number}{self.suffix}"


@dataclass(frozen=True)
class BalanceConfig:
    minimum: str = "0.00"
    maximum: str = "25.00"
    decimal_places: int = 2
    mode: BalanceMode = "positive_negative_zero"


@dataclass(frozen=True)
class SandboxExceptionCounts:
    unmatched_odin: int = 0
    duplicate_odin_id_pairs: int = 0
    duplicate_lunchtab_identifier: int = 0
    name_validation_failures: int = 0
    ambiguous_name_fallbacks: int = 0
    multiple_odin_to_one_lunchtab: int = 0
    malformed_missing_fields: int = 0
    malformed_invalid_balances: int = 0
    blank_family_codes: int = 0
    missing_initial_family_codes: int = 0
    duplicate_initial_family_codes: int = 0
    invalid_initial_amounts: int = 0


@dataclass(frozen=True)
class SandboxConfig:
    preset: str = "Clean baseline"
    total_odin_rows: int = 20
    total_lunchtab_rows: int = 25
    matchable_rows: int = 20
    odin_id: IdentifierConvention = IdentifierConvention(prefix="ODN-", start=1000, zero_pad=5)
    lunchtab_barcode: IdentifierConvention = IdentifierConvention(
        prefix="ODN-",
        start=1000,
        zero_pad=5,
    )
    family_code: IdentifierConvention = IdentifierConvention(prefix="FAM-", start=5000, zero_pad=5)
    family_grouping: FamilyGrouping = "mixed"
    shared_family_size: int = 2
    balance: BalanceConfig = BalanceConfig()
    seed: int = 424242
    output_root: Path = default_output_root() / "Sandbox Data"
    exceptions: SandboxExceptionCounts = SandboxExceptionCounts()


@dataclass(frozen=True)
class ExpectedSummary:
    odin_rows: int
    lunchtab_rows: int
    initial_balance_rows: int
    valid_odin_rows: int
    malformed_odin_rows: int
    matched_rows: int
    reconciliation_exceptions: int
    manual_review_exceptions: int
    exception_reasons: dict[str, int]
    initial_balances_blocked: bool


@dataclass(frozen=True)
class SandboxOutputPaths:
    odin_workbook: Path
    lunchtab_users: Path
    initial_balances: Path
    expected_summary: Path
    manifest: Path


@dataclass(frozen=True)
class SandboxPack:
    run_dir: Path
    paths: SandboxOutputPaths
    expected: ExpectedSummary


@dataclass(frozen=True)
class VerificationSummary:
    reconciliation_passed: bool
    initial_balances_passed: bool
    reconciliation_run_dir: Path
    initial_balances_run_dir: Path
    matched_rows: int
    reconciliation_exceptions: int
    manual_review_exceptions: int
    initial_balances_blocked: bool
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class SandboxVerificationResult:
    pack: SandboxPack
    verification: VerificationSummary | None = None


@dataclass(frozen=True)
class _SyntheticPerson:
    first: str
    preferred: str
    surname: str

    @property
    def student(self) -> str:
        return f"{self.surname}, {self.preferred or self.first}"


@dataclass(frozen=True)
class _GeneratedRows:
    odin_rows: list[list[str]]
    lunchtab_rows: list[dict[str, str]]


def preset_config(name: str, *, output_root: Path | None = None) -> SandboxConfig:
    if name not in PRESET_NAMES:
        raise ValueError(f"Unknown sandbox preset: {name}")
    root = output_root or (default_output_root() / "Sandbox Data")
    config = SandboxConfig(preset=name, output_root=root)
    if name == "Clean baseline":
        return config
    if name == "Reconciliation exceptions":
        return replace(
            config,
            total_odin_rows=30,
            total_lunchtab_rows=36,
            matchable_rows=20,
            exceptions=SandboxExceptionCounts(
                unmatched_odin=2,
                duplicate_odin_id_pairs=1,
                duplicate_lunchtab_identifier=1,
                name_validation_failures=2,
                ambiguous_name_fallbacks=1,
                multiple_odin_to_one_lunchtab=1,
            ),
        )
    if name == "Malformed source rows":
        return replace(
            config,
            total_odin_rows=25,
            total_lunchtab_rows=30,
            matchable_rows=20,
            exceptions=SandboxExceptionCounts(
                malformed_missing_fields=3,
                malformed_invalid_balances=2,
            ),
        )
    if name == "InitialBalances blockers":
        return replace(
            config,
            total_odin_rows=20,
            total_lunchtab_rows=30,
            matchable_rows=20,
            exceptions=SandboxExceptionCounts(
                blank_family_codes=1,
                missing_initial_family_codes=1,
                duplicate_initial_family_codes=1,
                invalid_initial_amounts=1,
            ),
        )
    return replace(
        config,
        total_odin_rows=36,
        total_lunchtab_rows=46,
        matchable_rows=24,
        exceptions=SandboxExceptionCounts(
            unmatched_odin=2,
            duplicate_odin_id_pairs=1,
            duplicate_lunchtab_identifier=1,
            name_validation_failures=2,
            ambiguous_name_fallbacks=1,
            multiple_odin_to_one_lunchtab=1,
            malformed_missing_fields=1,
            malformed_invalid_balances=1,
            blank_family_codes=1,
            missing_initial_family_codes=1,
            duplicate_initial_family_codes=1,
            invalid_initial_amounts=1,
        ),
    )


def validate_config(config: SandboxConfig) -> None:
    if config.preset not in PRESET_NAMES:
        raise ValueError(f"Unknown sandbox preset: {config.preset}")
    if config.total_odin_rows < 1 or config.total_lunchtab_rows < 1:
        raise ValueError("Total row counts must be positive.")
    if config.matchable_rows < 0:
        raise ValueError("Matchable rows cannot be negative.")
    if config.matchable_rows > config.total_odin_rows:
        raise ValueError("Matchable rows cannot exceed total Odin rows.")
    if config.matchable_rows > config.total_lunchtab_rows:
        raise ValueError("Matchable rows cannot exceed total LunchTab rows.")
    if config.shared_family_size < 1:
        raise ValueError("Shared family size must be positive.")
    if config.balance.decimal_places < 0 or config.balance.decimal_places > 4:
        raise ValueError("Decimal places must be between 0 and 4.")
    minimum = Decimal(config.balance.minimum)
    maximum = Decimal(config.balance.maximum)
    if minimum > maximum:
        raise ValueError("Minimum balance cannot exceed maximum balance.")
    if _required_odin_rows(config) > config.total_odin_rows:
        raise ValueError("Exception counts require more Odin rows than configured.")
    if _required_lunchtab_rows(config) > config.total_lunchtab_rows:
        raise ValueError("Exception counts require more LunchTab rows than configured.")


def generate_sandbox_pack(
    config: SandboxConfig,
    *,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> SandboxPack:
    validate_config(config)
    output_root = config.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = choose_run_dir(output_root, now())
    staging_dir = output_root / f".sandbox-staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()
    try:
        rows = _generate_rows(config)
        odin_path = staging_dir / "Sandbox Odin Account Balance Report.xlsx"
        lunchtab_path = staging_dir / "Sandbox Lunchtab Users.csv"
        initial_path = staging_dir / "Sandbox InitialBalances.csv"
        expected_path = staging_dir / "Sandbox Expected Summary.json"
        manifest_path = staging_dir / "sandbox-manifest.json"
        _write_odin_workbook(odin_path, rows.odin_rows)
        _write_csv(lunchtab_path, LUNCHTAB_HEADERS, rows.lunchtab_rows)
        initial_rows = _initial_balance_rows(rows.lunchtab_rows, config)
        _write_csv(initial_path, INITIAL_BALANCE_HEADERS, initial_rows)
        expected = _expected_summary(odin_path, lunchtab_path, initial_path)
        expected_path.write_text(
            json.dumps(asdict(expected), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(
                _manifest(config, expected, odin_path, lunchtab_path, initial_path),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        staging_dir.rename(run_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return SandboxPack(
        run_dir=run_dir,
        paths=SandboxOutputPaths(
            odin_workbook=run_dir / odin_path.name,
            lunchtab_users=run_dir / lunchtab_path.name,
            initial_balances=run_dir / initial_path.name,
            expected_summary=run_dir / expected_path.name,
            manifest=run_dir / manifest_path.name,
        ),
        expected=expected,
    )


def generate_and_verify_sandbox_pack(
    config: SandboxConfig,
    *,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> SandboxVerificationResult:
    pack = generate_sandbox_pack(config, now=now)
    verification = verify_sandbox_pack(pack)
    return SandboxVerificationResult(pack=pack, verification=verification)


def verify_sandbox_pack(pack: SandboxPack) -> VerificationSummary:
    reconciliation = run_managed_workflow(
        odin_path=pack.paths.odin_workbook,
        lunchtab_path=pack.paths.lunchtab_users,
        output_root=pack.run_dir / "Verification" / "Reconciliation",
    )
    initial = run_initial_balances_workflow(
        transfer_path=reconciliation.summary.output_paths.transfer,
        initial_balances_path=pack.paths.initial_balances,
        output_root=pack.run_dir / "Verification" / "InitialBalances",
    )
    mismatches = _verification_mismatches(pack.expected, reconciliation.summary, initial.summary)
    return VerificationSummary(
        reconciliation_passed=not any(item.startswith("reconciliation") for item in mismatches),
        initial_balances_passed=not any(item.startswith("InitialBalances") for item in mismatches),
        reconciliation_run_dir=reconciliation.run_dir,
        initial_balances_run_dir=initial.run_dir,
        matched_rows=reconciliation.summary.matched_by_id + reconciliation.summary.matched_by_name,
        reconciliation_exceptions=reconciliation.summary.exceptions,
        manual_review_exceptions=reconciliation.summary.manual_review_exceptions,
        initial_balances_blocked=initial.summary.blocked,
        mismatches=tuple(mismatches),
    )


def _required_odin_rows(config: SandboxConfig) -> int:
    exceptions = config.exceptions
    return (
        config.matchable_rows
        + exceptions.unmatched_odin
        + (exceptions.duplicate_odin_id_pairs * 2)
        + exceptions.duplicate_lunchtab_identifier
        + exceptions.name_validation_failures
        + exceptions.ambiguous_name_fallbacks
        + (exceptions.multiple_odin_to_one_lunchtab * 2)
        + exceptions.malformed_missing_fields
        + exceptions.malformed_invalid_balances
    )


def _required_lunchtab_rows(config: SandboxConfig) -> int:
    exceptions = config.exceptions
    return (
        config.matchable_rows
        + (exceptions.duplicate_lunchtab_identifier * 2)
        + exceptions.name_validation_failures
        + (exceptions.ambiguous_name_fallbacks * 2)
        + exceptions.multiple_odin_to_one_lunchtab
    )


def _generate_rows(config: SandboxConfig) -> _GeneratedRows:
    rng = random.Random(config.seed)
    odin_rows: list[list[str]] = []
    lunchtab_rows: list[dict[str, str]] = []
    people_index = 0

    for index in range(config.matchable_rows):
        person = _person(people_index)
        people_index += 1
        odin_id = config.odin_id.value(index)
        barcode = config.lunchtab_barcode.value(index)
        family_code = _family_code(config, index)
        balance = _balance(rng, config.balance, index)
        odin_rows.append(_odin_row(odin_id, person, balance))
        lunchtab_rows.append(_lunchtab_row(barcode, person, family_code, index))

    scenario_index = config.matchable_rows
    people_index = _add_reconciliation_exception_rows(
        config,
        rng,
        odin_rows,
        lunchtab_rows,
        people_index,
        scenario_index,
    )

    while len(odin_rows) < config.total_odin_rows:
        person = _person(people_index)
        people_index += 1
        odin_rows.append(
            _odin_row(
                f"UNMATCHED-{len(odin_rows) + 1:05d}",
                person,
                _balance(rng, config.balance, len(odin_rows)),
            )
        )

    while len(lunchtab_rows) < config.total_lunchtab_rows:
        person = _person(people_index)
        people_index += 1
        index = len(lunchtab_rows)
        lunchtab_rows.append(
            _lunchtab_row(
                f"LT-ONLY-{index + 1:05d}",
                person,
                f"LT-FAM-{index + 1:05d}",
                index,
            )
        )

    _apply_blank_family_codes(lunchtab_rows, config.exceptions.blank_family_codes)
    return _GeneratedRows(odin_rows=odin_rows, lunchtab_rows=lunchtab_rows)


def _add_reconciliation_exception_rows(
    config: SandboxConfig,
    rng: random.Random,
    odin_rows: list[list[str]],
    lunchtab_rows: list[dict[str, str]],
    people_index: int,
    scenario_index: int,
) -> int:
    exceptions = config.exceptions
    for _ in range(exceptions.unmatched_odin):
        person = _person(people_index)
        people_index += 1
        odin_rows.append(
            _odin_row(f"NO-LT-{len(odin_rows) + 1:05d}", person, _balance(rng, config.balance, 1))
        )

    for pair in range(exceptions.duplicate_odin_id_pairs):
        duplicate_id = f"DUP-ODIN-{pair + 1:04d}"
        for _ in range(2):
            person = _person(people_index)
            people_index += 1
            odin_rows.append(_odin_row(duplicate_id, person, _balance(rng, config.balance, 2)))

    for item in range(exceptions.duplicate_lunchtab_identifier):
        person = _person(people_index)
        people_index += 1
        barcode = f"DUP-LT-{item + 1:04d}"
        family_code = f"DUP-LT-FAM-{item + 1:04d}"
        odin_rows.append(_odin_row(barcode, person, _balance(rng, config.balance, 3)))
        lunchtab_rows.append(_lunchtab_row(barcode, person, family_code, scenario_index))
        lunchtab_rows.append(_lunchtab_row(barcode, person, f"{family_code}-B", scenario_index + 1))
        scenario_index += 2

    for item in range(exceptions.name_validation_failures):
        person = _person(people_index)
        wrong_person = _person(people_index + 500)
        people_index += 1
        barcode = f"NAME-FAIL-{item + 1:04d}"
        odin_rows.append(_odin_row(barcode, person, _balance(rng, config.balance, 4)))
        lunchtab_rows.append(
            _lunchtab_row(barcode, wrong_person, f"NAME-FAIL-FAM-{item + 1:04d}", scenario_index)
        )
        scenario_index += 1

    for item in range(exceptions.ambiguous_name_fallbacks):
        person = _person(people_index)
        people_index += 1
        odin_rows.append(
            _odin_row(f"AMBIG-ODIN-{item + 1:04d}", person, _balance(rng, config.balance, 5))
        )
        lunchtab_rows.append(
            _lunchtab_row(
                f"AMBIG-A-{item + 1:04d}", person, f"AMBIG-FAM-A-{item + 1:04d}", scenario_index
            )
        )
        lunchtab_rows.append(
            _lunchtab_row(
                f"AMBIG-B-{item + 1:04d}", person, f"AMBIG-FAM-B-{item + 1:04d}", scenario_index + 1
            )
        )
        scenario_index += 2

    for item in range(exceptions.multiple_odin_to_one_lunchtab):
        person = _person(people_index)
        people_index += 1
        lunchtab_rows.append(
            _lunchtab_row(
                f"MULTI-LT-{item + 1:04d}",
                person,
                f"MULTI-FAM-{item + 1:04d}",
                scenario_index,
            )
        )
        scenario_index += 1
        for source in range(2):
            odin_rows.append(
                _odin_row(
                    f"MULTI-ODIN-{item + 1:04d}-{source + 1}",
                    person,
                    _balance(rng, config.balance, 6),
                )
            )

    for item in range(exceptions.malformed_missing_fields):
        person = _person(people_index)
        people_index += 1
        row = _odin_row(f"MISSING-{item + 1:04d}", person, _balance(rng, config.balance, 7))
        row[5] = ""
        odin_rows.append(row)

    for item in range(exceptions.malformed_invalid_balances):
        person = _person(people_index)
        people_index += 1
        row = _odin_row(f"BAD-MONEY-{item + 1:04d}", person, _balance(rng, config.balance, 8))
        row[4] = "not-money"
        odin_rows.append(row)

    return people_index


def _person(index: int) -> _SyntheticPerson:
    first_names = (
        "Avery",
        "Blake",
        "Casey",
        "Devon",
        "Emery",
        "Finley",
        "Gray",
        "Harper",
        "Indigo",
        "Jordan",
        "Kai",
        "Logan",
        "Morgan",
        "Nova",
        "Oakley",
        "Parker",
    )
    surnames = (
        "Atlas",
        "Beacon",
        "Cedar",
        "Dover",
        "Elm",
        "Field",
        "Grove",
        "Harbor",
        "Iris",
        "Junction",
        "Keystone",
        "Lake",
        "Meadow",
        "North",
        "Orchard",
        "Prairie",
    )
    first = first_names[index % len(first_names)]
    surname = f"{surnames[(index // len(first_names)) % len(surnames)]}{index:03d}"
    preferred = first if index % 5 else ""
    return _SyntheticPerson(first=first, preferred=preferred, surname=surname)


def _balance(rng: random.Random, config: BalanceConfig, index: int) -> str:
    places = Decimal(10) ** -config.decimal_places
    if config.mode == "positive_negative_zero" and index % 9 == 0:
        amount = Decimal("0")
    else:
        low = Decimal(config.minimum)
        high = Decimal(config.maximum)
        cents = int((high - low) * 100)
        amount = low + (Decimal(rng.randint(0, max(cents, 0))) / Decimal("100"))
        if config.mode == "positive_negative_zero" and index % 7 == 0:
            amount = -amount
    return str(amount.quantize(places))


def _family_code(config: SandboxConfig, index: int) -> str:
    if config.family_grouping == "one_per_family":
        family_index = index
    elif config.family_grouping == "shared_every_n":
        family_index = index // config.shared_family_size
    else:
        family_index = index if index % 3 else index // max(config.shared_family_size, 1)
    return config.family_code.value(family_index)


def _odin_row(id_number: str, person: _SyntheticPerson, balance: str) -> list[str]:
    amount = Decimal(balance)
    deposits = amount + Decimal("10")
    spendings = Decimal("10")
    return [
        "Student Debit",
        id_number,
        str(deposits),
        str(spendings),
        balance,
        person.student,
    ]


def _lunchtab_row(
    barcode: str,
    person: _SyntheticPerson,
    family_code: str,
    index: int,
) -> dict[str, str]:
    username = f"sandbox{index:05d}"
    return {
        "FirstName": person.first,
        "PreferredName": person.preferred,
        "Surname": person.surname,
        "LoginBarcode": barcode,
        "ExternalId": f"EXT-{barcode}",
        "EmailAddress": f"{username}@sandbox.invalid",
        "DefaultFamilyCode": family_code,
        "DefaultFamilyBalanceAmount": "0.00",
    }


def _apply_blank_family_codes(rows: list[dict[str, str]], count: int) -> None:
    for row in rows[: max(count, 0)]:
        row["DefaultFamilyCode"] = ""


def _initial_balance_rows(
    lunchtab_rows: list[dict[str, str]],
    config: SandboxConfig,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for user in lunchtab_rows:
        code = user.get("DefaultFamilyCode", "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "FamilyName": f"Synthetic Family {len(rows) + 1:04d}",
                "FamilyCode": code,
                "Amount": "0.00",
            }
        )
    exceptions = config.exceptions
    for _ in range(min(exceptions.missing_initial_family_codes, len(rows))):
        rows.pop(0)
    for index in range(min(exceptions.duplicate_initial_family_codes, len(rows))):
        duplicate = dict(rows[index])
        duplicate["FamilyName"] = f"{duplicate['FamilyName']} Duplicate"
        rows.append(duplicate)
    for index in range(min(exceptions.invalid_initial_amounts, len(rows))):
        rows[index]["Amount"] = "not-money"
    return rows


def _write_odin_workbook(path: Path, rows: list[list[str]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Account Balance Report"
    sheet.append(["Account Balance Report"])
    sheet.append(["Synthetic sandbox data"])
    sheet.append([])
    sheet.append(list(ODIN_HEADERS))
    for row in rows:
        sheet.append(row)
    sheet.append(["", "Patron Count:", len(rows)])
    sheet.append(["", "Total Deposits:", "0"])
    sheet.append(["Account Code", "Account Type", "Balance"])
    workbook.save(path)


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _expected_summary(
    odin_path: Path,
    lunchtab_path: Path,
    initial_path: Path,
) -> ExpectedSummary:
    records, malformed = extract_odin_report(odin_path)
    _, users = read_csv(lunchtab_path)
    _, initial_rows = read_csv(initial_path)
    result = match_balances_detailed(records, users, malformed)
    reasons = Counter(row["Reason"] for row in result.exceptions)
    transfer_rows = result.output_users
    blocked = _initial_balances_would_block(transfer_rows, initial_rows)
    return ExpectedSummary(
        odin_rows=len(records) + len(malformed),
        lunchtab_rows=len(users),
        initial_balance_rows=len(initial_rows),
        valid_odin_rows=len(records),
        malformed_odin_rows=len(malformed),
        matched_rows=len(result.decisions),
        reconciliation_exceptions=len(result.exceptions),
        manual_review_exceptions=sum(
            row["Reason"] != "no Lunchtab match" for row in result.exceptions
        ),
        exception_reasons=dict(sorted(reasons.items())),
        initial_balances_blocked=blocked,
    )


def _initial_balances_would_block(
    transfer_rows: list[dict[str, str]],
    initial_rows: list[dict[str, str]],
) -> bool:
    codes_with_amount = [
        (row.get("DefaultFamilyCode") or "").strip()
        for row in transfer_rows
        if (row.get("OdinBalanceAmount") or "").strip()
    ]
    if any(not code for code in codes_with_amount):
        return True
    initial_codes = [row.get("FamilyCode", "").strip() for row in initial_rows]
    initial_counts = Counter(code for code in initial_codes if code)
    if any(initial_counts[code] != 1 for code in codes_with_amount):
        return True
    return any(row.get("Amount") == "not-money" for row in initial_rows)


def _manifest(
    config: SandboxConfig,
    expected: ExpectedSummary,
    odin_path: Path,
    lunchtab_path: Path,
    initial_path: Path,
) -> dict[str, object]:
    config_dict = asdict(config)
    config_dict["output_root"] = config.output_root.name
    return {
        "application": SANDBOX_APP_NAME,
        "generated_at": datetime.now().astimezone().isoformat(),
        "configuration": config_dict,
        "expected": asdict(expected),
        "generated_files": {
            "odin_workbook": odin_path.name,
            "lunchtab_users": lunchtab_path.name,
            "initial_balances": initial_path.name,
        },
    }


def _verification_mismatches(
    expected: ExpectedSummary,
    reconciliation,
    initial: InitialBalancesSummary,
) -> list[str]:
    mismatches: list[str] = []
    matched = reconciliation.matched_by_id + reconciliation.matched_by_name
    checks = {
        "reconciliation matched rows": (matched, expected.matched_rows),
        "reconciliation exceptions": (
            reconciliation.exceptions,
            expected.reconciliation_exceptions,
        ),
        "reconciliation manual review exceptions": (
            reconciliation.manual_review_exceptions,
            expected.manual_review_exceptions,
        ),
        "InitialBalances blocked": (initial.blocked, expected.initial_balances_blocked),
    }
    for label, (actual, wanted) in checks.items():
        if actual != wanted:
            mismatches.append(f"{label}: expected {wanted}, got {actual}")
    return mismatches


def transfer_path_from_reconciliation_dir(run_dir: Path) -> Path:
    return run_dir / FINAL_OUTPUT_NAME
