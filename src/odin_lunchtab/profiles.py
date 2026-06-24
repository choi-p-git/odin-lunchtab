from __future__ import annotations

import csv
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROFILE_SCHEMA_VERSION = 2
APPROVED_TARGET_FIELDS = ("LoginBarcode", "ExternalId", "EmailUsername")
TRANSFORM_KINDS = (
    "trim",
    "add_prefix",
    "remove_prefix",
    "add_suffix",
    "remove_suffix",
    "zero_pad",
    "strip_leading_zeros",
    "substring",
)
CROSSWALK_HEADERS = (
    "AccountType",
    "OdinId",
    "TargetField",
    "TargetValue",
    "AllowedEmailDomains",
)


@dataclass(frozen=True)
class TransformStep:
    kind: str
    value: str = ""
    start: int | None = None
    end: int | None = None

    def validate(self) -> None:
        if self.kind not in TRANSFORM_KINDS:
            raise ValueError(f"Unsupported transform: {self.kind}")
        if (
            self.kind
            in {
                "add_prefix",
                "remove_prefix",
                "add_suffix",
                "remove_suffix",
            }
            and not self.value
        ):
            raise ValueError(f"{self.kind} requires a value.")
        if self.kind == "zero_pad":
            try:
                width = int(self.value)
            except ValueError as error:
                raise ValueError("zero_pad requires a positive integer width.") from error
            if width < 1:
                raise ValueError("zero_pad requires a positive integer width.")
        if self.kind == "substring" and self.start is None and self.end is None:
            raise ValueError("substring requires a start or end position.")

    def apply(self, identifier: str) -> str:
        self.validate()
        if self.kind == "trim":
            return identifier.strip()
        if self.kind == "add_prefix":
            return f"{self.value}{identifier}"
        if self.kind == "remove_prefix":
            return (
                identifier[len(self.value) :] if identifier.startswith(self.value) else identifier
            )
        if self.kind == "add_suffix":
            return f"{identifier}{self.value}"
        if self.kind == "remove_suffix":
            return identifier[: -len(self.value)] if identifier.endswith(self.value) else identifier
        if self.kind == "zero_pad":
            return identifier.zfill(int(self.value))
        if self.kind == "strip_leading_zeros":
            return identifier.lstrip("0") or "0"
        return identifier[slice(self.start, self.end)]


@dataclass(frozen=True)
class MatchingRule:
    name: str
    target_field: str = "LoginBarcode"
    account_types: tuple[str, ...] = ()
    transforms: tuple[TransformStep, ...] = ()
    enabled: bool = True
    source_field: str = "ID Number"
    allowed_email_domains: tuple[str, ...] = ()

    def applies_to(self, account_type: str) -> bool:
        return self.enabled and (not self.account_types or account_type in self.account_types)

    def transform(self, identifier: str) -> str:
        value = identifier
        for step in self.transforms:
            value = step.apply(value)
        return value

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Every matching rule requires a name.")
        if self.source_field != "ID Number":
            raise ValueError("V1 matching rules support only the Odin ID Number source field.")
        if self.target_field not in APPROVED_TARGET_FIELDS:
            raise ValueError(f"Unsupported Lunchtab target field: {self.target_field}")
        if self.target_field != "EmailUsername" and self.allowed_email_domains:
            raise ValueError("Email-domain filters require the EmailUsername target.")
        for domain in self.allowed_email_domains:
            if not valid_email_domain(domain):
                raise ValueError(f"Invalid email domain: {domain}")
        for step in self.transforms:
            step.validate()


@dataclass(frozen=True)
class CrosswalkEntry:
    account_type: str
    odin_id: str
    target_field: str
    target_value: str
    allowed_email_domains: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.account_type.strip() or not self.odin_id.strip():
            raise ValueError("Crosswalk account type and Odin ID are required.")
        if self.target_field not in APPROVED_TARGET_FIELDS:
            raise ValueError(f"Unsupported crosswalk target field: {self.target_field}")
        if not self.target_value.strip():
            raise ValueError("Crosswalk target value is required.")
        if self.target_field != "EmailUsername" and self.allowed_email_domains:
            raise ValueError("Email-domain filters require the EmailUsername target.")
        for domain in self.allowed_email_domains:
            if not valid_email_domain(domain):
                raise ValueError(f"Invalid email domain: {domain}")


@dataclass(frozen=True)
class MatchingProfile:
    name: str
    description: str = ""
    rules: tuple[MatchingRule, ...] = ()
    crosswalk: tuple[CrosswalkEntry, ...] = ()
    name_fallback_account_types: tuple[str, ...] = ()
    name_fallback_all: bool = False
    profile_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: int = PROFILE_SCHEMA_VERSION
    read_only: bool = False

    def allows_name_fallback(self, account_type: str) -> bool:
        return self.name_fallback_all or account_type in self.name_fallback_account_types

    def validate(self) -> None:
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported profile schema version: {self.schema_version}. "
                f"Expected {PROFILE_SCHEMA_VERSION}."
            )
        if not self.name.strip():
            raise ValueError("Profile name is required.")
        enabled_names: set[str] = set()
        for rule in self.rules:
            rule.validate()
            key = rule.name.strip().casefold()
            if key in enabled_names:
                raise ValueError(f"Duplicate rule name: {rule.name}")
            enabled_names.add(key)
        crosswalk_keys: set[tuple[str, str]] = set()
        for entry in self.crosswalk:
            entry.validate()
            key = (entry.account_type, entry.odin_id)
            if key in crosswalk_keys:
                raise ValueError(
                    f"Duplicate crosswalk source identity: {entry.account_type} / {entry.odin_id}"
                )
            crosswalk_keys.add(key)


LEGACY_DEFAULT_PROFILE = MatchingProfile(
    profile_id="legacy-default",
    name="Legacy Default",
    description="Exact Odin ID to Lunchtab LoginBarcode, then unique-name fallback.",
    rules=(MatchingRule(name="Exact LoginBarcode"),),
    name_fallback_all=True,
    read_only=True,
)


def valid_email_domain(domain: str) -> bool:
    value = domain.strip().casefold()
    return (
        bool(value)
        and "@" not in value
        and not value.startswith(".")
        and not value.endswith(".")
        and ".." not in value
        and all(part and re.fullmatch(r"[a-z0-9-]+", part) for part in value.split("."))
    )


def parse_email_address(value: str) -> tuple[str, str] | None:
    address = value.strip()
    if address.count("@") != 1:
        return None
    username, domain = address.split("@", 1)
    username = username.strip()
    domain = domain.strip().casefold()
    if not username or not valid_email_domain(domain):
        return None
    return username, domain


def profile_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "Odin Lunchtab" / "profiles"


def profile_to_dict(profile: MatchingProfile) -> dict[str, Any]:
    return asdict(profile)


def profile_from_dict(data: dict[str, Any], *, imported: bool = False) -> MatchingProfile:
    schema_version = data.get("schema_version", 1)
    if schema_version not in {1, PROFILE_SCHEMA_VERSION}:
        raise ValueError(
            f"Unsupported profile schema version: {schema_version}. "
            f"Expected 1 or {PROFILE_SCHEMA_VERSION}."
        )
    rules = tuple(
        MatchingRule(
            name=item["name"],
            target_field=item.get("target_field", "LoginBarcode"),
            account_types=tuple(item.get("account_types", ())),
            transforms=tuple(TransformStep(**step) for step in item.get("transforms", ())),
            enabled=item.get("enabled", True),
            source_field=item.get("source_field", "ID Number"),
            allowed_email_domains=tuple(
                domain.strip().casefold()
                for domain in item.get("allowed_email_domains", ())
                if domain.strip()
            ),
        )
        for item in data.get("rules", ())
    )
    crosswalk = tuple(
        CrosswalkEntry(
            account_type=item["account_type"],
            odin_id=item["odin_id"],
            target_field=item["target_field"],
            target_value=item["target_value"],
            allowed_email_domains=tuple(
                domain.strip().casefold()
                for domain in item.get("allowed_email_domains", ())
                if domain.strip()
            ),
        )
        for item in data.get("crosswalk", ())
    )
    profile = MatchingProfile(
        profile_id=str(uuid.uuid4()) if imported else data.get("profile_id", str(uuid.uuid4())),
        schema_version=PROFILE_SCHEMA_VERSION,
        name=data["name"],
        description=data.get("description", ""),
        rules=rules,
        crosswalk=crosswalk,
        name_fallback_account_types=tuple(data.get("name_fallback_account_types", ())),
        name_fallback_all=data.get("name_fallback_all", False),
        read_only=False if imported else data.get("read_only", False),
    )
    profile.validate()
    return profile


def load_profile(path: Path, *, imported: bool = False) -> MatchingProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read matching profile: {path}") from error
    if not isinstance(data, dict):
        raise ValueError("Matching profile must contain a JSON object.")
    return profile_from_dict(data, imported=imported)


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-")
    return stem or "matching-profile"


def save_profile(profile: MatchingProfile, directory: Path | None = None) -> Path:
    profile.validate()
    if profile.read_only:
        raise ValueError("The Legacy Default profile cannot be modified.")
    directory = directory or profile_directory()
    directory.mkdir(parents=True, exist_ok=True)
    for existing in list_profiles(directory)[1:]:
        if (
            existing.profile_id != profile.profile_id
            and existing.name.casefold() == profile.name.casefold()
        ):
            raise ValueError(f"A profile named '{profile.name}' already exists.")
    path = directory / f"{_safe_filename(profile.name)}-{profile.profile_id}.json"
    for old_path in directory.glob(f"*-{profile.profile_id}.json"):
        if old_path != path:
            old_path.unlink()
    path.write_text(json.dumps(profile_to_dict(profile), indent=2), encoding="utf-8")
    return path


def list_profiles(directory: Path | None = None) -> list[MatchingProfile]:
    directory = directory or profile_directory()
    profiles = [LEGACY_DEFAULT_PROFILE]
    if not directory.is_dir():
        return profiles
    for path in sorted(directory.glob("*.json")):
        try:
            profiles.append(load_profile(path))
        except ValueError:
            continue
    return profiles


def delete_profile(profile: MatchingProfile, directory: Path | None = None) -> None:
    if profile.read_only:
        raise ValueError("The Legacy Default profile cannot be deleted.")
    directory = directory or profile_directory()
    for path in directory.glob(f"*-{profile.profile_id}.json"):
        path.unlink()


def duplicate_profile(profile: MatchingProfile, name: str) -> MatchingProfile:
    duplicate = MatchingProfile(
        name=name,
        description=profile.description,
        rules=profile.rules,
        crosswalk=profile.crosswalk,
        name_fallback_account_types=profile.name_fallback_account_types,
        name_fallback_all=profile.name_fallback_all,
    )
    duplicate.validate()
    return duplicate


def export_profile(profile: MatchingProfile, path: Path) -> None:
    path.write_text(json.dumps(profile_to_dict(profile), indent=2), encoding="utf-8")


def import_profile(path: Path) -> MatchingProfile:
    return load_profile(path, imported=True)


def export_crosswalk(profile: MatchingProfile, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CROSSWALK_HEADERS)
        writer.writeheader()
        for entry in profile.crosswalk:
            writer.writerow(
                {
                    "AccountType": entry.account_type,
                    "OdinId": entry.odin_id,
                    "TargetField": entry.target_field,
                    "TargetValue": entry.target_value,
                    "AllowedEmailDomains": " | ".join(entry.allowed_email_domains),
                }
            )


def import_crosswalk(path: Path) -> tuple[CrosswalkEntry, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != CROSSWALK_HEADERS:
            raise ValueError("Crosswalk CSV headers must be: " + ", ".join(CROSSWALK_HEADERS))
        entries = tuple(
            CrosswalkEntry(
                account_type=row["AccountType"].strip(),
                odin_id=row["OdinId"].strip(),
                target_field=row["TargetField"].strip(),
                target_value=row["TargetValue"].strip(),
                allowed_email_domains=tuple(
                    domain.strip().casefold()
                    for domain in row["AllowedEmailDomains"].split("|")
                    if domain.strip()
                ),
            )
            for row in reader
        )
    for entry in entries:
        entry.validate()
    return entries
