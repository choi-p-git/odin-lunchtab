from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from odin_lunchtab.profiles import (
    LEGACY_DEFAULT_PROFILE,
    MatchingProfile,
    parse_email_address,
)
from odin_lunchtab.workflow import (
    MatchDecision,
    OutputPaths,
    RunSummary,
    extract_odin_report,
    match_balances_detailed,
    read_csv,
    read_csv_with_metadata,
    run_workflow,
)

APP_NAME = "Odin to Lunchtab Balance Transfer"
MANIFEST_NAME = "run-manifest.json"
REQUIRED_LUNCHTAB_HEADERS = {
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "DefaultFamilyCode",
    "DefaultFamilyBalanceAmount",
}


@dataclass(frozen=True)
class InputInspection:
    odin_path: Path
    lunchtab_path: Path
    odin_rows: int
    malformed_odin_rows: int
    lunchtab_rows: int
    account_types: tuple[str, ...] = ()
    email_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfilePreview:
    profile_name: str
    matched: int
    crosswalk_matches: int
    rule_matches: int
    name_matches: int
    conflicts: int
    unmatched: int
    manual_review: int
    changed_from_legacy: int
    matches_by_rule: dict[str, int]
    samples: tuple[str, ...]


@dataclass(frozen=True)
class ManagedRunResult:
    run_dir: Path
    summary: RunSummary
    manifest_path: Path


def application_version() -> str:
    try:
        return version("odin-lunchtab")
    except PackageNotFoundError:
        return "0.0.0"


def default_output_root() -> Path:
    return Path.home() / "Documents" / "Odin Lunchtab Transfers"


def inspect_inputs(
    odin_path: Path,
    lunchtab_path: Path,
    profile: MatchingProfile | None = None,
) -> InputInspection:
    profile = profile or LEGACY_DEFAULT_PROFILE
    profile.validate()
    if odin_path.suffix.casefold() != ".xlsx":
        raise ValueError("The Odin report must be an .xlsx workbook.")
    if lunchtab_path.suffix.casefold() != ".csv":
        raise ValueError("The Lunchtab export must be a .csv file.")
    if not odin_path.is_file():
        raise FileNotFoundError(f"Odin report does not exist: {odin_path}")
    if not lunchtab_path.is_file():
        raise FileNotFoundError(f"Lunchtab export does not exist: {lunchtab_path}")

    records, malformed = extract_odin_report(odin_path)
    headers, users = read_csv(lunchtab_path)
    missing = sorted(REQUIRED_LUNCHTAB_HEADERS - set(headers))
    profile_fields = {
        "EmailAddress" if rule.target_field == "EmailUsername" else rule.target_field
        for rule in profile.rules
        if rule.enabled
    } | {
        "EmailAddress" if entry.target_field == "EmailUsername" else entry.target_field
        for entry in profile.crosswalk
    }
    missing.extend(sorted(profile_fields - set(headers)))
    missing = sorted(set(missing))
    if missing:
        raise ValueError(f"Lunchtab export is missing required columns: {', '.join(missing)}")
    return InputInspection(
        odin_path=odin_path,
        lunchtab_path=lunchtab_path,
        odin_rows=len(records),
        malformed_odin_rows=len(malformed),
        lunchtab_rows=len(users),
        account_types=tuple(sorted({record.account_type for record in records})),
        email_domains=tuple(
            sorted(
                {
                    parsed[1]
                    for user in users
                    if (parsed := parse_email_address(user.get("EmailAddress", "")))
                }
            )
        ),
    )


def _decision_targets(decisions: list[MatchDecision]) -> dict[tuple[str, str], int]:
    return {
        (decision.record.account_type, decision.record.id_number): decision.target_index
        for decision in decisions
    }


def preview_profile(
    odin_path: Path,
    lunchtab_path: Path,
    profile: MatchingProfile,
) -> ProfilePreview:
    profile.validate()
    inspect_inputs(odin_path, lunchtab_path, profile)
    records, malformed = extract_odin_report(odin_path)
    _, users = read_csv(lunchtab_path)
    result = match_balances_detailed(records, users, malformed, profile)
    legacy = match_balances_detailed(records, users, malformed, LEGACY_DEFAULT_PROFILE)
    current_targets = _decision_targets(result.decisions)
    legacy_targets = _decision_targets(legacy.decisions)
    changed = sum(
        current_targets.get(key) != legacy_targets.get(key)
        for key in current_targets.keys() | legacy_targets.keys()
    )
    reasons = [row["Reason"] for row in result.exceptions]
    conflicts = sum(
        reason
        in {
            "matching rules resolved to different Lunchtab users",
            "duplicate Lunchtab identifier",
            "multiple Odin records matched one Lunchtab user",
        }
        for reason in reasons
    )
    unmatched = sum(
        reason in {"no Lunchtab match", "no configured identifier match"} for reason in reasons
    )
    samples = tuple(
        f"{decision.record.account_type}: {decision.record.id_number} → "
        f"{decision.transformed_value or 'name fallback'} ({decision.rule_name})"
        for decision in result.decisions[:10]
    )
    return ProfilePreview(
        profile_name=profile.name,
        matched=len(result.decisions),
        crosswalk_matches=result.counts["crosswalk"],
        rule_matches=result.counts["id"] + result.counts["rule"],
        name_matches=result.counts["name"],
        conflicts=conflicts,
        unmatched=unmatched,
        manual_review=sum(reason != "no Lunchtab match" for reason in reasons),
        changed_from_legacy=changed,
        matches_by_rule={
            key.removeprefix("rule:"): value
            for key, value in result.counts.items()
            if key.startswith("rule:")
        },
        samples=samples,
    )


def choose_run_dir(output_root: Path, started_at: datetime) -> Path:
    base_name = started_at.strftime("%Y-%m-%d_%H%M%S")
    candidate = output_root / base_name
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def _rebased_paths(paths: OutputPaths, run_dir: Path) -> OutputPaths:
    return OutputPaths(
        cleaned=run_dir / paths.cleaned.name,
        processed=run_dir / paths.processed.name,
        transfer=run_dir / paths.transfer.name,
        exceptions=run_dir / paths.exceptions.name,
        manual_review_exceptions=run_dir / paths.manual_review_exceptions.name,
        match_audit=(run_dir / paths.match_audit.name if paths.match_audit is not None else None),
        audit_control=(
            run_dir / paths.audit_control.name if paths.audit_control is not None else None
        ),
    )


def _manifest(
    *,
    started_at: datetime,
    completed_at: datetime,
    odin_path: Path,
    lunchtab_path: Path,
    summary: RunSummary,
) -> dict[str, object]:
    counts = asdict(summary)
    counts.pop("output_paths")
    _, _, lunchtab_encoding = read_csv_with_metadata(lunchtab_path)
    return {
        "application": APP_NAME,
        "version": application_version(),
        "started_at": started_at.astimezone().isoformat(),
        "completed_at": completed_at.astimezone().isoformat(),
        "inputs": {
            "odin": odin_path.name,
            "lunchtab": {
                "name": lunchtab_path.name,
                "encoding": lunchtab_encoding.encoding,
                "used_fallback": lunchtab_encoding.used_fallback,
            },
        },
        "counts": counts,
        "matching_profile": {
            "name": summary.profile_name,
            "schema_version": summary.profile_schema_version,
            "matches_by_rule": summary.matches_by_rule or {},
        },
        "audit_control": {
            "status": summary.audit_control_status,
            "report": (
                summary.output_paths.audit_control.name
                if summary.output_paths.audit_control is not None
                else None
            ),
        },
        "generated_files": [
            path.name for path in asdict(summary.output_paths).values() if path is not None
        ],
    }


def run_managed_workflow(
    *,
    odin_path: Path,
    lunchtab_path: Path,
    output_root: Path | None = None,
    profile: MatchingProfile | None = None,
    now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> ManagedRunResult:
    profile = profile or LEGACY_DEFAULT_PROFILE
    profile.validate()
    inspect_inputs(odin_path, lunchtab_path, profile)
    output_root = output_root or default_output_root()
    output_root.mkdir(parents=True, exist_ok=True)
    started_at = now()
    run_dir = choose_run_dir(output_root, started_at)
    staging_dir = output_root / f".staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()

    try:
        summary = run_workflow(
            raw_data_dir=odin_path.parent,
            output_dir=staging_dir,
            odin_path=odin_path,
            lunchtab_path=lunchtab_path,
            profile=profile,
        )
        completed_at = now()
        manifest_path = staging_dir / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(
                _manifest(
                    started_at=started_at,
                    completed_at=completed_at,
                    odin_path=odin_path,
                    lunchtab_path=lunchtab_path,
                    summary=summary,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        staging_dir.rename(run_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    rebased = replace(summary, output_paths=_rebased_paths(summary.output_paths, run_dir))
    return ManagedRunResult(
        run_dir=run_dir,
        summary=rebased,
        manifest_path=run_dir / MANIFEST_NAME,
    )
