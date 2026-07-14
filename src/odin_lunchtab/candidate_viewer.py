from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from odin_lunchtab.exception_candidates import CANDIDATE_HEADERS
from odin_lunchtab.workflow import FINAL_OUTPUT_NAME, read_csv

MANUAL_EDIT_CHECKLIST_NAME = "Manual Edit Checklist - Actionable Candidates.csv"
AMBIGUOUS_EDIT_CHECKLIST_NAME = "Manual Edit Checklist - Ambiguous Candidates.csv"
PROPOSED_TRANSFER_NAME = "Proposed Edited Transfer - Candidate Selections.csv"
PROPOSED_TRANSFER_AUDIT_NAME = "Proposed Transfer Selection Audit.csv"
MANUAL_EDIT_CHECKLIST_HEADERS = [
    "Selected",
    "SelectionNote",
    "ReviewCategory",
    "Odin ID Number",
    "Odin Student",
    "Odin Balance",
    "Candidate Position",
    "Candidate Count",
    "Confidence",
    "Candidate LoginBarcode",
    "Candidate FamilyCode",
    "Candidate Name",
    "Transfer RowNumber",
    "Transfer Current OdinBalanceAmount",
    "Suggested OdinBalanceAmount",
    "Evidence",
    "ManualAction",
    "AuditNote",
]
PROPOSED_TRANSFER_AUDIT_HEADERS = [
    "Odin ID Number",
    "Odin Student",
    "Candidate LoginBarcode",
    "Candidate Name",
    "Transfer RowNumber",
    "Original OdinBalanceAmount",
    "Proposed OdinBalanceAmount",
    "Evidence",
    "Status",
    "Notes",
]


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


@dataclass(frozen=True)
class ManualEditChecklistOutput:
    actionable_path: Path
    ambiguous_path: Path
    actionable_rows: int
    ambiguous_rows: int


@dataclass(frozen=True)
class CandidateSelectionIssue:
    severity: str
    issue_type: str
    odin_id: str
    odin_student: str
    candidate_login_barcode: str
    message: str


@dataclass(frozen=True)
class CandidateSelectionValidation:
    selected_rows: tuple[CandidateMatchRow, ...]
    issues: tuple[CandidateSelectionIssue, ...]

    @property
    def blocked(self) -> bool:
        return any(issue.severity == "BLOCKING" for issue in self.issues)


@dataclass(frozen=True)
class CandidateReviewGroup:
    group_key: str
    reason: str
    odin_id: str
    odin_student: str
    odin_balance: str
    rows: tuple[CandidateMatchRow, ...]

    @property
    def actionable_rows(self) -> tuple[CandidateMatchRow, ...]:
        return tuple(row for row in self.rows if row.is_actionable)

    @property
    def is_actionable(self) -> bool:
        return bool(self.actionable_rows)

    @property
    def requires_choice(self) -> bool:
        return len(self.actionable_rows) > 1


@dataclass(frozen=True)
class CandidateReviewProgress:
    total_groups: int
    resolved_groups: int
    selected_groups: int
    skipped_groups: int
    unresolved_groups: int
    selected_candidates: int


@dataclass(frozen=True)
class CandidateReviewState:
    groups: tuple[CandidateReviewGroup, ...]
    selections: dict[str, str]
    skipped_groups: frozenset[str]

    @property
    def progress(self) -> CandidateReviewProgress:
        selected_groups = 0
        selected_candidates = 0
        for group in self.groups:
            group_selected = [
                row
                for row in group.actionable_rows
                if self.selections.get(row.login_barcode) == "yes"
            ]
            if group_selected:
                selected_groups += 1
                selected_candidates += len(group_selected)
        skipped_groups = len(self.skipped_groups)
        resolved_groups = selected_groups + skipped_groups
        return CandidateReviewProgress(
            total_groups=len(self.groups),
            resolved_groups=resolved_groups,
            selected_groups=selected_groups,
            skipped_groups=skipped_groups,
            unresolved_groups=max(len(self.groups) - resolved_groups, 0),
            selected_candidates=selected_candidates,
        )

    def select_candidate(self, group_key: str, login_barcode: str) -> CandidateReviewState:
        group = self._group_by_key(group_key)
        if group is None:
            raise ValueError(f"Unknown review group: {group_key}")
        selected = next(
            (row for row in group.actionable_rows if row.login_barcode == login_barcode),
            None,
        )
        if selected is None:
            raise ValueError(f"Candidate {login_barcode} is not actionable for this group.")
        selections = dict(self.selections)
        for row in group.actionable_rows:
            selections[row.login_barcode] = "yes" if row.login_barcode == login_barcode else ""
        return CandidateReviewState(
            groups=self.groups,
            selections=selections,
            skipped_groups=frozenset(key for key in self.skipped_groups if key != group_key),
        )

    def skip_group(self, group_key: str) -> CandidateReviewState:
        group = self._group_by_key(group_key)
        if group is None:
            raise ValueError(f"Unknown review group: {group_key}")
        selections = dict(self.selections)
        for row in group.actionable_rows:
            selections[row.login_barcode] = ""
        return CandidateReviewState(
            groups=self.groups,
            selections=selections,
            skipped_groups=frozenset({*self.skipped_groups, group_key}),
        )

    def clear_group(self, group_key: str) -> CandidateReviewState:
        group = self._group_by_key(group_key)
        if group is None:
            raise ValueError(f"Unknown review group: {group_key}")
        selections = dict(self.selections)
        for row in group.actionable_rows:
            selections[row.login_barcode] = ""
        return CandidateReviewState(
            groups=self.groups,
            selections=selections,
            skipped_groups=frozenset(key for key in self.skipped_groups if key != group_key),
        )

    def selection_values(self) -> dict[str, str]:
        return {
            row.login_barcode: self.selections.get(row.login_barcode, "")
            for group in self.groups
            for row in group.actionable_rows
            if row.login_barcode
        }

    def validation(self) -> CandidateSelectionValidation:
        return validate_candidate_selections(
            [row for group in self.groups for row in group.rows],
            self.selection_values(),
            require_ambiguous_selection=False,
        )

    def _group_by_key(self, group_key: str) -> CandidateReviewGroup | None:
        return next((group for group in self.groups if group.group_key == group_key), None)


@dataclass(frozen=True)
class ProposedTransferOutput:
    proposed_transfer_path: Path
    audit_path: Path
    updated_rows: int
    transfer_path: Path


def default_transfer_path_for_candidate_report(candidate_report_path: Path) -> Path | None:
    transfer_path = candidate_report_path.parent / FINAL_OUTPUT_NAME
    return transfer_path if transfer_path.is_file() else None


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


def build_candidate_review_groups(
    rows: list[CandidateMatchRow],
) -> tuple[CandidateReviewGroup, ...]:
    grouped: dict[str, list[CandidateMatchRow]] = {}
    for row in rows:
        if row.is_actionable and row.exception_group_key:
            grouped.setdefault(row.exception_group_key, []).append(row)
    return tuple(
        CandidateReviewGroup(
            group_key=group_key,
            reason=group_rows[0].reason,
            odin_id=group_rows[0].odin_id,
            odin_student=group_rows[0].odin_student,
            odin_balance=group_rows[0].odin_balance,
            rows=tuple(group_rows),
        )
        for group_key, group_rows in grouped.items()
    )


def create_candidate_review_state(rows: list[CandidateMatchRow]) -> CandidateReviewState:
    groups = build_candidate_review_groups(rows)
    return CandidateReviewState(groups=groups, selections={}, skipped_groups=frozenset())


def _checklist_category(row: CandidateMatchRow) -> str:
    return (
        "Ambiguous - choose one candidate"
        if row.has_ambiguous_actionable_group
        else "Ready - single actionable candidate"
    )


def _checklist_row(row: CandidateMatchRow) -> dict[str, str]:
    return {
        "Selected": "",
        "SelectionNote": "",
        "ReviewCategory": _checklist_category(row),
        "Odin ID Number": row.odin_id,
        "Odin Student": row.odin_student,
        "Odin Balance": row.odin_balance,
        "Candidate Position": str(row.actionable_group_position),
        "Candidate Count": str(row.actionable_group_count),
        "Confidence": row.confidence,
        "Candidate LoginBarcode": row.login_barcode,
        "Candidate FamilyCode": row.family_code,
        "Candidate Name": row.candidate_name,
        "Transfer RowNumber": row.transfer_row_number,
        "Transfer Current OdinBalanceAmount": row.transfer_current_balance,
        "Suggested OdinBalanceAmount": row.suggested_balance,
        "Evidence": row.evidence,
        "ManualAction": (
            f"After verification, edit transfer row {row.transfer_row_number} "
            f"OdinBalanceAmount to {row.suggested_balance}."
        ),
        "AuditNote": (
            "Verify the candidate before editing. This checklist is advisory and does not "
            "change the transfer CSV."
        ),
    }


def write_manual_edit_checklists(
    rows: list[CandidateMatchRow],
    *,
    output_dir: Path,
) -> ManualEditChecklistOutput:
    output_dir.mkdir(parents=True, exist_ok=True)
    actionable_path = output_dir / MANUAL_EDIT_CHECKLIST_NAME
    ambiguous_path = output_dir / AMBIGUOUS_EDIT_CHECKLIST_NAME
    actionable_rows = [
        _checklist_row(row)
        for row in rows
        if row.is_actionable and not row.has_ambiguous_actionable_group
    ]
    ambiguous_rows = [_checklist_row(row) for row in rows if row.has_ambiguous_actionable_group]
    for path, checklist_rows in (
        (actionable_path, actionable_rows),
        (ambiguous_path, ambiguous_rows),
    ):
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=MANUAL_EDIT_CHECKLIST_HEADERS,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(checklist_rows)
    return ManualEditChecklistOutput(
        actionable_path=actionable_path,
        ambiguous_path=ambiguous_path,
        actionable_rows=len(actionable_rows),
        ambiguous_rows=len(ambiguous_rows),
    )


def _selected_value(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if not normalized:
        return False
    if normalized in {"y", "yes", "true", "1", "x", "selected"}:
        return True
    if normalized in {"n", "no", "false", "0"}:
        return False
    return None


def validate_candidate_selections(
    rows: list[CandidateMatchRow],
    selections: dict[str, str],
    *,
    require_ambiguous_selection: bool = True,
) -> CandidateSelectionValidation:
    rows_by_barcode = {row.login_barcode: row for row in rows}
    issues: list[CandidateSelectionIssue] = []
    selected_rows: list[CandidateMatchRow] = []
    for barcode, value in selections.items():
        selected = _selected_value(value)
        row = rows_by_barcode.get(barcode)
        if row is None:
            issues.append(
                CandidateSelectionIssue(
                    severity="BLOCKING",
                    issue_type="unknown candidate",
                    odin_id="",
                    odin_student="",
                    candidate_login_barcode=barcode,
                    message="Selected candidate does not exist in the candidate report.",
                )
            )
            continue
        if selected is None:
            issues.append(
                CandidateSelectionIssue(
                    severity="BLOCKING",
                    issue_type="invalid selection value",
                    odin_id=row.odin_id,
                    odin_student=row.odin_student,
                    candidate_login_barcode=barcode,
                    message="Selection value must be blank, yes/no, true/false, 1/0, x, or selected.",
                )
            )
            continue
        if not selected:
            continue
        if not row.is_actionable:
            issues.append(
                CandidateSelectionIssue(
                    severity="BLOCKING",
                    issue_type="non-actionable selected",
                    odin_id=row.odin_id,
                    odin_student=row.odin_student,
                    candidate_login_barcode=barcode,
                    message="Selected candidate is not actionable and cannot be applied safely.",
                )
            )
            continue
        selected_rows.append(row)

    selected_by_group: dict[str, list[CandidateMatchRow]] = {}
    for row in selected_rows:
        selected_by_group.setdefault(row.exception_group_key, []).append(row)

    actionable_groups = {
        row.exception_group_key: row
        for row in rows
        if row.is_actionable and row.exception_group_key
    }
    for group_key, exemplar in actionable_groups.items():
        group_selected = selected_by_group.get(group_key, [])
        if (
            require_ambiguous_selection
            and exemplar.has_ambiguous_actionable_group
            and not group_selected
        ):
            issues.append(
                CandidateSelectionIssue(
                    severity="BLOCKING",
                    issue_type="ambiguous group missing selection",
                    odin_id=exemplar.odin_id,
                    odin_student=exemplar.odin_student,
                    candidate_login_barcode="",
                    message="Ambiguous actionable group requires exactly one selected candidate.",
                )
            )
        if len(group_selected) > 1:
            issues.append(
                CandidateSelectionIssue(
                    severity="BLOCKING",
                    issue_type="multiple selections for group",
                    odin_id=exemplar.odin_id,
                    odin_student=exemplar.odin_student,
                    candidate_login_barcode=" | ".join(row.login_barcode for row in group_selected),
                    message="Only one candidate may be selected for a single Odin exception.",
                )
            )

    return CandidateSelectionValidation(
        selected_rows=tuple(selected_rows),
        issues=tuple(issues),
    )


def read_candidate_selection_values(path: Path) -> dict[str, str]:
    headers, rows = read_csv(path)
    required = {"Candidate LoginBarcode", "Selected"}
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(
            "Candidate selection CSV is missing required columns: " + ", ".join(missing)
        )
    return {
        row.get("Candidate LoginBarcode", "").strip(): row.get("Selected", "")
        for row in rows
        if row.get("Candidate LoginBarcode", "").strip()
    }


def validate_candidate_selection_file(
    rows: list[CandidateMatchRow],
    selection_path: Path,
) -> CandidateSelectionValidation:
    return validate_candidate_selections(rows, read_candidate_selection_values(selection_path))


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _selection_blocker_text(validation: CandidateSelectionValidation) -> str:
    issue_types = ", ".join(issue.issue_type for issue in validation.issues)
    return f"Candidate selections are blocked: {issue_types}"


def write_proposed_transfer_from_selections(
    *,
    transfer_path: Path,
    candidate_rows: list[CandidateMatchRow],
    selections: dict[str, str],
    output_dir: Path,
) -> ProposedTransferOutput:
    validation = validate_candidate_selections(candidate_rows, selections)
    if validation.blocked:
        raise ValueError(_selection_blocker_text(validation))

    headers, transfer_rows = read_csv(transfer_path)
    required = {"LoginBarcode", "OdinBalanceAmount"}
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError("Transfer CSV is missing required columns: " + ", ".join(missing))

    output_rows = [dict(row) for row in transfer_rows]
    audit_rows: list[dict[str, str]] = []
    for row in validation.selected_rows:
        try:
            transfer_index = int(row.transfer_row_number) - 2
        except ValueError as error:
            raise ValueError(
                f"Selected candidate {row.login_barcode} has invalid transfer row number."
            ) from error
        if transfer_index < 0 or transfer_index >= len(output_rows):
            raise ValueError(
                f"Selected candidate {row.login_barcode} points outside the transfer CSV."
            )
        transfer_row = output_rows[transfer_index]
        if transfer_row.get("LoginBarcode", "").strip() != row.login_barcode:
            raise ValueError(
                f"Selected candidate {row.login_barcode} no longer matches transfer row "
                f"{row.transfer_row_number}."
            )
        current_balance = transfer_row.get("OdinBalanceAmount", "")
        if current_balance.strip():
            raise ValueError(
                f"Transfer row {row.transfer_row_number} already has OdinBalanceAmount."
            )
        transfer_row["OdinBalanceAmount"] = row.suggested_balance
        audit_rows.append(
            {
                "Odin ID Number": row.odin_id,
                "Odin Student": row.odin_student,
                "Candidate LoginBarcode": row.login_barcode,
                "Candidate Name": row.candidate_name,
                "Transfer RowNumber": row.transfer_row_number,
                "Original OdinBalanceAmount": current_balance,
                "Proposed OdinBalanceAmount": row.suggested_balance,
                "Evidence": row.evidence,
                "Status": "UPDATED",
                "Notes": "Selected candidate balance applied to proposed transfer copy.",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    proposed_path = output_dir / PROPOSED_TRANSFER_NAME
    audit_path = output_dir / PROPOSED_TRANSFER_AUDIT_NAME
    _write_csv(proposed_path, headers, output_rows)
    _write_csv(audit_path, PROPOSED_TRANSFER_AUDIT_HEADERS, audit_rows)
    return ProposedTransferOutput(
        proposed_transfer_path=proposed_path,
        audit_path=audit_path,
        updated_rows=len(audit_rows),
        transfer_path=transfer_path,
    )
