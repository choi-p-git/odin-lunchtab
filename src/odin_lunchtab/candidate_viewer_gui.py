from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from odin_lunchtab.candidate_viewer import (
    CandidateMatchRow,
    filter_candidate_match_rows,
    load_candidate_match_rows,
    summarize_candidate_match_rows,
)
from odin_lunchtab.desktop import friendly_error, open_path
from odin_lunchtab.ui_helpers import add_tree_scrollbars, size_and_center


class CandidateMatchesWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, path: Path) -> None:
        super().__init__(parent)
        self.path = path
        self.rows = load_candidate_match_rows(path)
        self.filtered_rows: list[CandidateMatchRow] = []
        self.search_text = tk.StringVar()
        self.confidence_text = tk.StringVar(value="All")
        self.actionable_only = tk.BooleanVar(value=False)
        self.ambiguous_only = tk.BooleanVar(value=False)
        self.status_text = tk.StringVar()
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
        ttk.Button(footer, text="Open CSV", command=self._open_csv).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(footer, text="Close", command=self.destroy).grid(row=0, column=3, padx=(8, 0))

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
        self._set_detail("Select a candidate row to inspect evidence.")

    def _selected_row(self) -> CandidateMatchRow | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.filtered_rows[int(selection[0])]

    def _select_row(self, _: tk.Event[tk.Misc] | None = None) -> None:
        row = self._selected_row()
        self._set_detail(
            row.detail_text if row is not None else "Select a candidate row to inspect evidence."
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

    def _open_csv(self) -> None:
        try:
            open_path(self.path)
        except Exception as error:
            messagebox.showerror("Manual Review Candidate Matches", friendly_error(error))
