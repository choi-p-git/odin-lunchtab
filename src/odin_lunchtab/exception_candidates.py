from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from odin_lunchtab.profiles import parse_email_address
from odin_lunchtab.workflow import (
    first_names_compatible,
    normalize_name,
    read_csv,
    split_student_name,
)

CANDIDATE_REPORT_NAME = "Manual Review Candidate Matches.csv"
CANDIDATE_HEADERS = [
    "Reason",
    "Odin ID Number",
    "Odin Student",
    "Odin Balance",
    "Candidate Rank",
    "Confidence",
    "Candidate LoginBarcode",
    "Candidate ExternalId",
    "Candidate FamilyCode",
    "Candidate Name",
    "Candidate EmailAddress",
    "Transfer RowNumber",
    "Transfer Current OdinBalanceAmount",
    "Suggested OdinBalanceAmount",
    "Transfer TraceStatus",
    "Score",
    "Evidence",
    "SourceArtifact",
    "Notes",
]
REQUIRED_EXCEPTION_HEADERS = {"Reason", "ID Number", "Balance", "Student"}
REQUIRED_LUNCHTAB_HEADERS = {
    "FirstName",
    "PreferredName",
    "Surname",
    "LoginBarcode",
    "DefaultFamilyCode",
}
REQUIRED_TRANSFER_HEADERS = {"LoginBarcode", "OdinBalanceAmount"}


@dataclass(frozen=True)
class CandidateReportSummary:
    exception_rows: int
    candidate_rows: int
    exceptions_with_candidates: int
    output_path: Path


@dataclass(frozen=True)
class _ScoredCandidate:
    score: int
    evidence: tuple[str, ...]
    user: dict[str, str]


@dataclass(frozen=True)
class _TransferTrace:
    row_number: str
    current_balance: str
    status: str


def _split_candidate_barcodes(value: str) -> set[str]:
    return {item.strip() for item in value.split("|") if item.strip()}


def _candidate_name(user: dict[str, str]) -> str:
    first = user.get("FirstName", "").strip()
    preferred = user.get("PreferredName", "").strip()
    surname = user.get("Surname", "").strip()
    if preferred and preferred != first:
        return f"{surname}, {first} ({preferred})".strip(", ")
    return f"{surname}, {first}".strip(", ")


def _email_username(user: dict[str, str]) -> str:
    parsed = parse_email_address(user.get("EmailAddress", ""))
    return parsed[0] if parsed else ""


def _confidence(score: int) -> str:
    if score >= 90:
        return "High"
    if score >= 70:
        return "Medium"
    return "Low"


def _score_candidate(
    exception: dict[str, str],
    user: dict[str, str],
    *,
    listed_candidate_barcodes: set[str],
) -> _ScoredCandidate | None:
    odin_id = exception.get("ID Number", "").strip()
    student = exception.get("Student", "").strip()
    try:
        odin_surname, odin_first = split_student_name(student)
    except ValueError:
        odin_surname = ""
        odin_first = ""

    score = 0
    evidence: list[str] = []
    login_barcode = user.get("LoginBarcode", "").strip()
    external_id = user.get("ExternalId", "").strip()
    email_username = _email_username(user)

    if login_barcode and login_barcode in listed_candidate_barcodes:
        score += 20
        evidence.append("listed by reconciliation exception")
    if odin_id and login_barcode == odin_id:
        score += 70
        evidence.append("LoginBarcode equals Odin ID")
    if odin_id and external_id == odin_id:
        score += 70
        evidence.append("ExternalId equals Odin ID")
    if odin_id and email_username.casefold() == odin_id.casefold():
        score += 65
        evidence.append("email username equals Odin ID")

    normalized_odin_surname = normalize_name(odin_surname)
    normalized_user_surname = normalize_name(user.get("Surname", ""))
    if normalized_odin_surname and normalized_odin_surname == normalized_user_surname:
        score += 35
        evidence.append("surname matches")
    elif normalized_odin_surname and normalized_user_surname:
        odin_tokens = set(normalized_odin_surname.split())
        user_tokens = set(normalized_user_surname.split())
        if odin_tokens & user_tokens:
            score += 15
            evidence.append("surname token overlaps")

    first_name = user.get("FirstName", "")
    preferred_name = user.get("PreferredName", "")
    if odin_first and first_names_compatible(odin_first, first_name):
        score += 30
        evidence.append("first name matches")
    elif (
        odin_first
        and first_name
        and normalize_name(odin_first)[:1] == normalize_name(first_name)[:1]
    ):
        score += 10
        evidence.append("first initial matches")
    if odin_first and preferred_name and first_names_compatible(odin_first, preferred_name):
        score += 30
        evidence.append("preferred name matches")

    if score < 50:
        return None
    return _ScoredCandidate(min(score, 100), tuple(evidence), user)


def _candidate_row(
    *,
    exception: dict[str, str],
    candidate: _ScoredCandidate,
    rank: int,
    source_artifact: Path,
    transfer_trace: _TransferTrace,
) -> dict[str, str]:
    user = candidate.user
    return {
        "Reason": exception.get("Reason", ""),
        "Odin ID Number": exception.get("ID Number", ""),
        "Odin Student": exception.get("Student", ""),
        "Odin Balance": exception.get("Balance", ""),
        "Candidate Rank": str(rank),
        "Confidence": _confidence(candidate.score),
        "Candidate LoginBarcode": user.get("LoginBarcode", ""),
        "Candidate ExternalId": user.get("ExternalId", ""),
        "Candidate FamilyCode": user.get("DefaultFamilyCode", ""),
        "Candidate Name": _candidate_name(user),
        "Candidate EmailAddress": user.get("EmailAddress", ""),
        "Transfer RowNumber": transfer_trace.row_number,
        "Transfer Current OdinBalanceAmount": transfer_trace.current_balance,
        "Suggested OdinBalanceAmount": exception.get("Balance", ""),
        "Transfer TraceStatus": transfer_trace.status,
        "Score": str(candidate.score),
        "Evidence": " | ".join(candidate.evidence),
        "SourceArtifact": source_artifact.name,
        "Notes": "Advisory candidate only; verify manually before editing the transfer CSV.",
    }


def _transfer_index(
    transfer_path: Path | None,
) -> dict[str, list[tuple[int, dict[str, str]]]] | None:
    if transfer_path is None:
        return None
    headers, rows = read_csv(transfer_path)
    missing = sorted(REQUIRED_TRANSFER_HEADERS - set(headers))
    if missing:
        raise ValueError("Transfer CSV is missing required columns: " + ", ".join(missing))
    index: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for offset, row in enumerate(rows, start=2):
        barcode = row.get("LoginBarcode", "").strip()
        if barcode:
            index.setdefault(barcode, []).append((offset, row))
    return index


def _transfer_trace(
    candidate: _ScoredCandidate,
    transfer_rows_by_barcode: dict[str, list[tuple[int, dict[str, str]]]] | None,
) -> _TransferTrace:
    if transfer_rows_by_barcode is None:
        return _TransferTrace("", "", "not requested")
    barcode = candidate.user.get("LoginBarcode", "").strip()
    if not barcode:
        return _TransferTrace("", "", "candidate has blank LoginBarcode")
    matches = transfer_rows_by_barcode.get(barcode, [])
    if not matches:
        return _TransferTrace("", "", "candidate not found in transfer")
    if len(matches) > 1:
        return _TransferTrace("", "", "duplicate LoginBarcode in transfer")
    row_number, row = matches[0]
    return _TransferTrace(
        str(row_number),
        row.get("OdinBalanceAmount", ""),
        "found unique transfer row",
    )


def write_manual_review_candidate_report(
    *,
    manual_review_exceptions_path: Path,
    lunchtab_path: Path,
    output_dir: Path,
    transfer_path: Path | None = None,
    max_candidates_per_exception: int = 5,
) -> CandidateReportSummary:
    exception_headers, exceptions = read_csv(manual_review_exceptions_path)
    lunchtab_headers, users = read_csv(lunchtab_path)
    missing_exception = sorted(REQUIRED_EXCEPTION_HEADERS - set(exception_headers))
    if missing_exception:
        raise ValueError(
            "Manual-review exceptions CSV is missing required columns: "
            + ", ".join(missing_exception)
        )
    missing_lunchtab = sorted(REQUIRED_LUNCHTAB_HEADERS - set(lunchtab_headers))
    if missing_lunchtab:
        raise ValueError("Lunchtab CSV is missing required columns: " + ", ".join(missing_lunchtab))
    if max_candidates_per_exception < 1:
        raise ValueError("max_candidates_per_exception must be at least 1.")
    transfer_rows_by_barcode = _transfer_index(transfer_path)

    candidate_rows: list[dict[str, str]] = []
    exceptions_with_candidates = 0
    for exception in exceptions:
        listed_candidate_barcodes = _split_candidate_barcodes(
            exception.get("Candidate LoginBarcodes", "")
        )
        candidates = [
            scored
            for user in users
            if (
                scored := _score_candidate(
                    exception,
                    user,
                    listed_candidate_barcodes=listed_candidate_barcodes,
                )
            )
            is not None
        ]
        candidates.sort(
            key=lambda item: (
                -item.score,
                item.user.get("Surname", ""),
                item.user.get("FirstName", ""),
                item.user.get("LoginBarcode", ""),
            )
        )
        if candidates:
            exceptions_with_candidates += 1
        for rank, candidate in enumerate(candidates[:max_candidates_per_exception], start=1):
            candidate_rows.append(
                _candidate_row(
                    exception=exception,
                    candidate=candidate,
                    rank=rank,
                    source_artifact=manual_review_exceptions_path,
                    transfer_trace=_transfer_trace(candidate, transfer_rows_by_barcode),
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / CANDIDATE_REPORT_NAME
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidate_rows)
    return CandidateReportSummary(
        exception_rows=len(exceptions),
        candidate_rows=len(candidate_rows),
        exceptions_with_candidates=exceptions_with_candidates,
        output_path=output_path,
    )
