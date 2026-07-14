from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from odin_lunchtab.candidate_viewer import (
    CandidateMatchRow,
    CandidateReviewState,
    ProposedTransferOutput,
    create_candidate_review_state,
    default_transfer_path_for_candidate_report,
    filter_candidate_match_rows,
    load_candidate_match_rows,
    read_candidate_selection_values,
    summarize_candidate_match_rows,
    write_candidate_review_decisions,
    write_manual_edit_checklists,
    write_proposed_transfer_from_selections,
)
from odin_lunchtab.desktop import friendly_error, open_path
from odin_lunchtab.ui_helpers import add_tree_scrollbars, size_and_center

WorkerEvent = tuple[str, ProposedTransferOutput | Exception]


class CandidateMatchesWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, path: Path) -> None:
        super().__init__(parent)
        self.path = path
        self.rows = load_candidate_match_rows(path)
        self.filtered_rows: list[CandidateMatchRow] = []
        self.review_state: CandidateReviewState = create_candidate_review_state(self.rows)
        self.worker_events: queue.Queue[WorkerEvent] = queue.Queue()
        self.worker_poll_after: str | None = None
        self.proposed_transfer_running = False
        self.search_text = tk.StringVar()
        self.confidence_text = tk.StringVar(value="All")
        self.actionable_only = tk.BooleanVar(value=False)
        self.ambiguous_only = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar()
        self.review_text = tk.StringVar()
        self.detail_text = tk.StringVar(value="Select a candidate row to inspect evidence.")

        self.title("Manual Review Candidate Matches")
        size_and_center(self, 1100, 720)
        self.transient(parent)
        self._build()
        self._apply_filter()
        self.search_text.trace_add("write", lambda *_: self._apply_filter())
        self.confidence_text.trace_add("write", lambda *_: self._apply_filter())
        self.actionable_only.trace_add("write", lambda *_: self._apply_filter())
        self.ambiguous_only.trace_add("write", lambda *_: self._apply_filter())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._schedule_worker_poll()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(16, 14, 16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(
            header,
            text="Manual Review Candidate Matches",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(
            header,
            text=(
                "Search ranked advisory candidates before manually editing the "
                "reconciled transfer CSV."
            ),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 12))
        ttk.Label(header, text="Search").grid(row=2, column=0, sticky="w")
        search = ttk.Entry(header, textvariable=self.search_text)
        search.grid(row=2, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(header, text="Confidence").grid(row=2, column=2, sticky="w")
        ttk.Combobox(
            header,
            textvariable=self.confidence_text,
            values=("All", "High", "Medium", "Low"),
            state="readonly",
            width=12,
        ).grid(row=2, column=3, sticky="ew", padx=(8, 0))
        ttk.Checkbutton(
            header,
            text="Actionable only",
            variable=self.actionable_only,
        ).grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            header,
            text="Ambiguous only",
            variable=self.ambiguous_only,
        ).grid(row=3, column=2, columnspan=2, sticky="w", pady=(8, 0))

        body = ttk.PanedWindow(self, orient="vertical")
        body.grid(row=1, column=0, sticky="nsew", padx=16)

        table_frame = ttk.Frame(body)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=(
                "review",
                "rank",
                "confidence",
                "odin",
                "candidate",
                "barcode",
                "family",
                "transfer_row",
                "current_balance",
                "suggested_balance",
                "ambiguity",
                "score",
                "evidence",
            ),
            show="headings",
            height=12,
        )
        headings = {
            "review": ("Review", 120),
            "rank": ("Rank", 60),
            "confidence": ("Confidence", 100),
            "odin": ("Odin student", 210),
            "candidate": ("Candidate", 210),
            "barcode": ("Barcode", 110),
            "family": ("Family", 120),
            "transfer_row": ("Transfer row", 100),
            "current_balance": ("Current balance", 120),
            "suggested_balance": ("Suggested balance", 130),
            "ambiguity": ("Ambiguity", 130),
            "score": ("Score", 70),
            "evidence": ("Evidence", 360),
        }
        for column, (label, width) in headings.items():
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=60, stretch=column == "evidence")
        add_tree_scrollbars(table_frame, self.tree)
        self.tree.bind("<<TreeviewSelect>>", self._select_row)
        body.add(table_frame, weight=3)

        detail_frame = ttk.LabelFrame(body, text="Selected candidate evidence", padding=10)
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.detail = tk.Text(
            detail_frame,
            height=9,
            wrap="word",
            state="disabled",
            borderwidth=0,
            highlightthickness=0,
        )
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")
        body.add(detail_frame, weight=1)

        footer = ttk.Frame(self, padding=(16, 10, 16, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_text).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Copy selected details", command=self._copy_selected).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(footer, text="Export checklist", command=self._export_checklist).grid(
            row=0, column=2, padx=(8, 0)
        )
        self.propose_button = ttk.Button(
            footer,
            text="Create proposed transfer",
            command=self._create_proposed_transfer,
        )
        self.propose_button.grid(row=0, column=3, padx=(8, 0))
        ttk.Button(footer, text="Open CSV", command=self._open_csv).grid(
            row=0, column=4, padx=(8, 0)
        )
        ttk.Button(footer, text="Close", command=self.destroy).grid(row=0, column=5, padx=(8, 0))

        ttk.Label(footer, textvariable=self.review_text).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(footer, text="Select candidate", command=self._select_candidate_review).grid(
            row=1, column=1, padx=(8, 0), pady=(8, 0)
        )
        ttk.Button(footer, text="Skip group", command=self._skip_review_group).grid(
            row=1, column=2, padx=(8, 0), pady=(8, 0)
        )
        ttk.Button(footer, text="Clear group", command=self._clear_review_group).grid(
            row=1, column=3, padx=(8, 0), pady=(8, 0)
        )

        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.grid(row=2, column=1, columnspan=5, sticky="e", pady=(8, 0))
        self.progress.grid_remove()

    def _set_proposed_transfer_busy(self, busy: bool) -> None:
        self.proposed_transfer_running = busy
        self.propose_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.grid()
            self.progress.start(10)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _schedule_worker_poll(self) -> None:
        self.worker_poll_after = self.after(100, self._poll_worker_events)

    def _on_destroy(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is not self or self.worker_poll_after is None:
            return
        self.after_cancel(self.worker_poll_after)
        self.worker_poll_after = None

    def _poll_worker_events(self) -> None:
        self.worker_poll_after = None
        while True:
            try:
                event_name, payload = self.worker_events.get_nowait()
            except queue.Empty:
                break
            if event_name == "proposed_transfer_created":
                self._set_proposed_transfer_busy(False)
                output = payload
                if isinstance(output, Exception):
                    messagebox.showerror("Manual Review Candidate Matches", friendly_error(output))
                    continue
                self.status_text.set(
                    f"Proposed transfer created: {output.updated_rows} selected update(s)."
                )
                messagebox.showinfo(
                    "Manual Review Candidate Matches",
                    "Proposed transfer files were created:\n\n"
                    f"- {output.proposed_transfer_path.name}\n"
                    f"- {output.audit_path.name}\n"
                    + (
                        f"- {output.review_decisions_path.name}\n"
                        if output.review_decisions_path is not None
                        else ""
                    )
                    + "\n"
                    f"Source transfer: {output.transfer_path.name}",
                )
            elif event_name == "proposed_transfer_failed":
                self._set_proposed_transfer_busy(False)
                error = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
                messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))
        if self.winfo_exists():
            self._schedule_worker_poll()

    def _create_proposed_transfer(self) -> None:
        if self.proposed_transfer_running:
            return
        progress = self.review_state.progress
        use_review_state = False
        selection_path: str | None = None
        if progress.selected_candidates:
            use_review_state = messagebox.askyesno(
                "Manual Review Candidate Matches",
                "Create the proposed transfer from the in-app selected candidates?\n\n"
                f"Selected candidates: {progress.selected_candidates}\n"
                f"Skipped groups: {progress.skipped_groups}\n"
                f"Unresolved groups: {progress.unresolved_groups}\n\n"
                "Choose No to select a reviewed checklist CSV instead.",
            )
        if not use_review_state:
            selection_path = filedialog.askopenfilename(
                title="Select reviewed manual edit checklist",
                initialdir=str(self.path.parent),
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            )
            if not selection_path:
                return
        transfer_file = default_transfer_path_for_candidate_report(self.path)
        if transfer_file is None:
            selected_transfer_path = filedialog.askopenfilename(
                title="Select original transfer CSV",
                initialdir=str(self.path.parent),
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            )
            if not selected_transfer_path:
                return
            transfer_file = Path(selected_transfer_path)
        elif not messagebox.askyesno(
            "Manual Review Candidate Matches",
            "Use the matching transfer CSV from this run folder?\n\n"
            f"{transfer_file.name}\n\n"
            "Choose No to select a different transfer CSV.",
        ):
            selected_transfer_path = filedialog.askopenfilename(
                title="Select original transfer CSV",
                initialdir=str(self.path.parent),
                initialfile=transfer_file.name,
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            )
            if not selected_transfer_path:
                return
            transfer_file = Path(selected_transfer_path)
        if not transfer_file:
            return
        output_dir = filedialog.askdirectory(
            title="Choose folder for proposed transfer files",
            initialdir=str(self.path.parent),
        )
        if not output_dir:
            return

        self._set_proposed_transfer_busy(True)
        self.status_text.set("Creating proposed transfer copy from reviewed selections...")

        selection_file = Path(selection_path) if selection_path else None
        selections = self.review_state.selection_values() if use_review_state else None
        review_state = self.review_state if use_review_state else None
        output_folder = Path(output_dir)

        def worker() -> None:
            try:
                selected_values = (
                    selections
                    if selections is not None
                    else read_candidate_selection_values(selection_file)
                )
                output = write_proposed_transfer_from_selections(
                    transfer_path=transfer_file,
                    candidate_rows=self.rows,
                    selections=selected_values,
                    output_dir=output_folder,
                    require_ambiguous_selection=not use_review_state,
                )
                if review_state is not None:
                    decision_output = write_candidate_review_decisions(
                        review_state,
                        output_dir=output_folder,
                    )
                    output = replace(
                        output,
                        review_decisions_path=decision_output.path,
                        review_decision_rows=decision_output.rows,
                    )
            except Exception as error:
                self.worker_events.put(("proposed_transfer_failed", error))
            else:
                self.worker_events.put(("proposed_transfer_created", output))

        threading.Thread(target=worker, daemon=True).start()

    def _review_status_for_row(self, row: CandidateMatchRow) -> str:
        if not row.is_actionable:
            return "Not actionable"
        if self.review_state.selections.get(row.login_barcode) == "yes":
            return "Selected"
        if row.exception_group_key in self.review_state.skipped_groups:
            return "Skipped"
        return "Needs choice" if row.has_ambiguous_actionable_group else "Ready"

    def _review_detail_for_row(self, row: CandidateMatchRow) -> str:
        return "\n".join(
            [
                row.detail_text,
                "",
                f"Review status: {self._review_status_for_row(row)}",
            ]
        )

    def _refresh_review_status(self) -> None:
        progress = self.review_state.progress
        self.review_text.set(
            "Review progress: "
            f"{progress.resolved_groups}/{progress.total_groups} groups resolved "
            f"({progress.selected_groups} selected, {progress.skipped_groups} skipped, "
            f"{progress.unresolved_groups} unresolved)."
        )

    def _selected_actionable_row(self, action: str) -> CandidateMatchRow | None:
        row = self._selected_row()
        if row is None:
            messagebox.showinfo(
                "Manual Review Candidate Matches",
                f"Select an actionable candidate row before choosing {action}.",
            )
            return None
        if not row.is_actionable:
            messagebox.showinfo(
                "Manual Review Candidate Matches",
                "This row is not actionable. Choose a candidate with a unique transfer row, "
                "blank current OdinBalanceAmount, and suggested Odin balance.",
            )
            return None
        return row

    def _select_candidate_review(self) -> None:
        row = self._selected_actionable_row("Select candidate")
        if row is None:
            return
        try:
            self.review_state = self.review_state.select_candidate(
                row.exception_group_key,
                row.login_barcode,
            )
        except ValueError as error:
            messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))
            return
        self._apply_filter()
        self.status_text.set(f"Selected candidate {row.login_barcode} for this Odin exception.")

    def _skip_review_group(self) -> None:
        row = self._selected_actionable_row("Skip group")
        if row is None:
            return
        try:
            self.review_state = self.review_state.skip_group(row.exception_group_key)
        except ValueError as error:
            messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))
            return
        self._apply_filter()
        self.status_text.set(f"Skipped candidate group for {row.odin_student}.")

    def _clear_review_group(self) -> None:
        row = self._selected_actionable_row("Clear group")
        if row is None:
            return
        try:
            self.review_state = self.review_state.clear_group(row.exception_group_key)
        except ValueError as error:
            messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))
            return
        self._apply_filter()
        self.status_text.set(f"Cleared review choice for {row.odin_student}.")

    def _open_csv(self) -> None:
        try:
            open_path(self.path)
        except Exception as error:
            messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))

    def _apply_filter(self) -> None:
        self.filtered_rows = filter_candidate_match_rows(
            self.rows,
            query=self.search_text.get(),
            confidence=self.confidence_text.get(),
            actionable_only=self.actionable_only.get(),
            ambiguous_only=self.ambiguous_only.get(),
        )
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.filtered_rows):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    self._review_status_for_row(row),
                    row.rank,
                    row.confidence,
                    f"{row.odin_student} ({row.odin_id})",
                    row.candidate_name,
                    row.login_barcode,
                    row.family_code,
                    row.transfer_row_number,
                    row.transfer_current_balance,
                    row.suggested_balance,
                    (
                        f"{row.actionable_group_position} of {row.actionable_group_count}"
                        if row.is_actionable
                        else ""
                    ),
                    row.score,
                    row.evidence,
                ),
            )
        summary = summarize_candidate_match_rows(self.rows)
        self.status_text.set(
            f"Showing {len(self.filtered_rows)} of {len(self.rows)} candidate rows "
            f"({summary.actionable_rows} actionable; "
            f"{summary.ambiguous_actionable_groups} ambiguous groups) from {self.path.name}"
        )
        self._refresh_review_status()
        self._set_detail("Select a candidate row to inspect evidence.")

    def _selected_row(self) -> CandidateMatchRow | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.filtered_rows[int(selection[0])]

    def _select_row(self, _: tk.Event[tk.Misc] | None = None) -> None:
        row = self._selected_row()
        self._set_detail(
            self._review_detail_for_row(row)
            if row is not None
            else "Select a candidate row to inspect evidence."
        )

    def _set_detail(self, value: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", value)
        self.detail.configure(state="disabled")

    def _copy_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            messagebox.showinfo(
                "Manual Review Candidate Matches",
                "Select a candidate row before copying details.",
            )
            return
        self.clipboard_clear()
        self.clipboard_append(row.detail_text)
        self.status_text.set("Selected candidate details copied to the clipboard.")

    def _export_checklist(self) -> None:
        try:
            output = write_manual_edit_checklists(self.rows, output_dir=self.path.parent)
        except Exception as error:
            messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))
            return
        self.status_text.set(
            "Manual edit checklists exported: "
            f"{output.actionable_rows} ready row(s), {output.ambiguous_rows} ambiguous row(s)."
        )
        messagebox.showinfo(
            "Manual Review Candidate Matches",
            "Manual edit checklists were exported to the candidate report folder.",
        )
