from __future__ import annotations

from dataclasses import dataclass
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


def load_candidate_match_rows(path: Path) -> list[CandidateMatchRow]:
    headers, rows = read_csv(path)
    missing = [header for header in CANDIDATE_HEADERS if header not in headers]
    if missing:
        raise ValueError("Candidate match CSV is missing required columns: " + ", ".join(missing))
    return [
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


def filter_candidate_match_rows(
    rows: list[CandidateMatchRow],
    *,
    query: str = "",
    confidence: str = "All",
) -> list[CandidateMatchRow]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    confidence_filter = confidence.casefold()
    return [
        row
        for row in rows
        if (confidence_filter == "all" or row.confidence.casefold() == confidence_filter)
        and all(term in row.searchable_text for term in terms)
    ]
