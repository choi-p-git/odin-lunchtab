from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from odin_lunchtab.exception_candidates import CANDIDATE_HEADERS
from odin_lunchtab.workflow import read_csv


@dataclass(frozen=True)
class CandidateMatchRow:
    reason: str
    odin_id: str
    odin_student: str
    odin_balance: str
    rank: str
    confidence: str
    login_barcode: str
    external_id: str
    family_code: str
    candidate_name: str
    email: str
    transfer_row_number: str
    transfer_current_balance: str
    suggested_balance: str
    transfer_trace_status: str
    score: str
    evidence: str
    source_artifact: str
    notes: str
    exception_group_key: str = ""
    actionable_group_count: int = 0
    actionable_group_position: int = 0

    @property
    def is_actionable(self) -> bool:
        return (
            self.transfer_trace_status == "found unique transfer row"
            and bool(self.suggested_balance.strip())
            and not self.transfer_current_balance.strip()
        )

    @property
    def has_ambiguous_actionable_group(self) -> bool:
        return self.is_actionable and self.actionable_group_count > 1

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [
                self.reason,
                self.odin_id,
                self.odin_student,
                self.odin_balance,
                self.confidence,
                self.login_barcode,
                self.external_id,
                self.family_code,
                self.candidate_name,
                self.email,
                self.transfer_row_number,
                self.transfer_current_balance,
                self.suggested_balance,
                self.transfer_trace_status,
                self.score,
                self.evidence,
                self.notes,
                self.exception_group_key,
                str(self.actionable_group_count),
                str(self.actionable_group_position),
            ]
        ).casefold()

    @property
    def detail_text(self) -> str:
        return "\n".join(
            [
                f"Reason: {self.reason}",
                f"Odin ID Number: {self.odin_id}",
                f"Odin Student: {self.odin_student}",
                f"Odin Balance: {self.odin_balance}",
                f"Actionable candidate group: {self.actionable_group_position} of {self.actionable_group_count}"
                if self.is_actionable
                else "Actionable candidate group: not actionable",
                (
                    "Ambiguity: multiple actionable candidates for this Odin exception"
                    if self.has_ambiguous_actionable_group
                    else "Ambiguity: none detected for actionable candidates"
                    if self.is_actionable
                    else "Ambiguity: not applicable"
                ),
                "",
                f"Candidate rank: {self.rank}",
                f"Confidence: {self.confidence}",
                f"Score: {self.score}",
                f"Candidate name: {self.candidate_name}",
                f"LoginBarcode: {self.login_barcode}",
                f"ExternalId: {self.external_id}",
                f"FamilyCode: {self.family_code}",
                f"EmailAddress: {self.email}",
                "",
                f"Transfer RowNumber: {self.transfer_row_number}",
                f"Transfer Current OdinBalanceAmount: {self.transfer_current_balance}",
                f"Suggested OdinBalanceAmount: {self.suggested_balance}",
                f"Transfer TraceStatus: {self.transfer_trace_status}",
                "",
                f"Evidence: {self.evidence}",
                f"Source artifact: {self.source_artifact}",
                f"Notes: {self.notes}",
            ]
        )


@dataclass(frozen=True)
class CandidateMatchSummary:
    total_rows: int
    actionable_rows: int
    ambiguous_actionable_rows: int
    ambiguous_actionable_groups: int
    confidence_counts: dict[str, int]
    trace_status_counts: dict[str, int]


def _group_key(row: CandidateMatchRow) -> str:
    return "\u001f".join([row.reason, row.odin_id, row.odin_student, row.odin_balance])


def _with_group_metadata(rows: list[CandidateMatchRow]) -> list[CandidateMatchRow]:
    actionable_by_group = Counter(_group_key(row) for row in rows if row.is_actionable)
    position_by_group: Counter[str] = Counter()
    enriched: list[CandidateMatchRow] = []
    for row in rows:
        key = _group_key(row)
        if row.is_actionable:
            position_by_group[key] += 1
            position = position_by_group[key]
        else:
            position = 0
        enriched.append(
            replace(
                row,
                exception_group_key=key,
                actionable_group_count=actionable_by_group.get(key, 0),
                actionable_group_position=position,
            )
        )
    return enriched


def load_candidate_match_rows(path: Path) -> list[CandidateMatchRow]:
    headers, rows = read_csv(path)
    missing = [header for header in CANDIDATE_HEADERS if header not in headers]
    if missing:
        raise ValueError("Candidate match CSV is missing required columns: " + ", ".join(missing))
    return _with_group_metadata(
        [
            CandidateMatchRow(
                reason=row.get("Reason", ""),
                odin_id=row.get("Odin ID Number", ""),
                odin_student=row.get("Odin Student", ""),
                odin_balance=row.get("Odin Balance", ""),
                rank=row.get("Candidate Rank", ""),
                confidence=row.get("Confidence", ""),
                login_barcode=row.get("Candidate LoginBarcode", ""),
                external_id=row.get("Candidate ExternalId", ""),
                family_code=row.get("Candidate FamilyCode", ""),
                candidate_name=row.get("Candidate Name", ""),
                email=row.get("Candidate EmailAddress", ""),
                transfer_row_number=row.get("Transfer RowNumber", ""),
                transfer_current_balance=row.get("Transfer Current OdinBalanceAmount", ""),
                suggested_balance=row.get("Suggested OdinBalanceAmount", ""),
                transfer_trace_status=row.get("Transfer TraceStatus", ""),
                score=row.get("Score", ""),
                evidence=row.get("Evidence", ""),
                source_artifact=row.get("SourceArtifact", ""),
                notes=row.get("Notes", ""),
            )
            for row in rows
        ]
    )


def filter_candidate_match_rows(
    rows: list[CandidateMatchRow],
    *,
    query: str = "",
    confidence: str = "All",
    actionable_only: bool = False,
    ambiguous_only: bool = False,
) -> list[CandidateMatchRow]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    confidence_filter = confidence.casefold()
    return [
        row
        for row in rows
        if (confidence_filter == "all" or row.confidence.casefold() == confidence_filter)
        and (not actionable_only or row.is_actionable)
        and (not ambiguous_only or row.has_ambiguous_actionable_group)
        and all(term in row.searchable_text for term in terms)
    ]


def summarize_candidate_match_rows(rows: list[CandidateMatchRow]) -> CandidateMatchSummary:
    confidence_counts = Counter(row.confidence or "Blank" for row in rows)
    trace_status_counts = Counter(row.transfer_trace_status or "Blank" for row in rows)
    ambiguous_groups = {
        row.exception_group_key
        for row in rows
        if row.has_ambiguous_actionable_group and row.exception_group_key
    }
    return CandidateMatchSummary(
        total_rows=len(rows),
        actionable_rows=sum(row.is_actionable for row in rows),
        ambiguous_actionable_rows=sum(row.has_ambiguous_actionable_group for row in rows),
        ambiguous_actionable_groups=len(ambiguous_groups),
        confidence_counts=dict(sorted(confidence_counts.items())),
        trace_status_counts=dict(sorted(trace_status_counts.items())),
    )
