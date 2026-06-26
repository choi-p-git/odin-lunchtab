from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from odin_lunchtab.app_logging import configure_logging
from odin_lunchtab.desktop import friendly_error, open_path
from odin_lunchtab.gui_controller import (
    AppController,
    AppPhase,
    InitialBalancesController,
    InitialBalancesPhase,
    ManualReconciliationController,
    ManualReconciliationPhase,
)
from odin_lunchtab.initial_balances import (
    inspect_initial_balances_inputs,
    preflight_initial_balances_transfer,
    run_initial_balances_workflow,
)
from odin_lunchtab.managed import (
    ProfilePreview,
    default_output_root,
    inspect_inputs,
    preview_profile,
    run_managed_workflow,
)
from odin_lunchtab.manual_reconciliation import run_manual_reconciliation_workflow
from odin_lunchtab.profile_gui import PreviewWindow, ProfileManager
from odin_lunchtab.profiles import list_profiles
from odin_lunchtab.ui_helpers import (
    ScrollableFrame,
    size_and_center,
)

APP_TITLE = "Odin to Lunchtab Balance Transfer"


def resource_path(relative: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / relative


class BalanceTransferApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.controller = AppController(default_output_root())
        self.initial_controller = InitialBalancesController(default_output_root())
        self.manual_controller = ManualReconciliationController(default_output_root())
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.logger = configure_logging()
        self.profiles = list_profiles()
        self.preview: ProfilePreview | None = None

        root.title(APP_TITLE)
        size_and_center(root, 900, 720)
        icon = resource_path("assets/app.ico")
        if icon.is_file():
            root.iconbitmap(default=str(icon))

        self.odin_text = tk.StringVar()
        self.lunchtab_text = tk.StringVar()
        self.output_text = tk.StringVar(value=str(self.controller.state.output_root))
        self.status_text = tk.StringVar(value=self.controller.state.message)
        self.details_text = tk.StringVar(value="")
        self.profile_text = tk.StringVar(value=self.controller.state.profile.name)
        self.initial_transfer_text = tk.StringVar()
        self.initial_balances_text = tk.StringVar()
        self.initial_status_text = tk.StringVar(value=self.initial_controller.state.message)
        self.initial_details_text = tk.StringVar()
        self.manual_original_text = tk.StringVar()
        self.manual_edited_text = tk.StringVar()
        self.manual_status_text = tk.StringVar(value=self.manual_controller.state.message)
        self.manual_details_text = tk.StringVar()
        self._build()
        self._render()
        root.after(100, self._poll_events)

    def _build(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        reconciliation_tab = ttk.Frame(self.notebook)
        initial_balances_tab = ttk.Frame(self.notebook)
        manual_reconciliation_tab = ttk.Frame(self.notebook)
        self.notebook.add(reconciliation_tab, text="Odin Reconciliation")
        self.notebook.add(manual_reconciliation_tab, text="Manual Reconciliation Review")
        self.notebook.add(initial_balances_tab, text="InitialBalances Transfer")

        scroller = ScrollableFrame(reconciliation_tab, padding=22)
        scroller.pack(fill="both", expand=True)
        outer = scroller.content

        ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Safely match Odin balances into a copy of the Lunchtab users export.",
        ).pack(anchor="w", pady=(3, 20))

        files = ttk.LabelFrame(outer, text="Source files", padding=14)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        self._file_row(
            files,
            0,
            "Odin report",
            self.odin_text,
            self._choose_odin,
        )
        self._file_row(
            files,
            1,
            "Lunchtab export",
            self.lunchtab_text,
            self._choose_lunchtab,
        )
        self._file_row(
            files,
            2,
            "Save results in",
            self.output_text,
            self._choose_output,
        )
        ttk.Label(files, text="Matching profile", width=18).grid(
            row=3, column=0, sticky="w", pady=5
        )
        self.profile_combo = ttk.Combobox(
            files,
            textvariable=self.profile_text,
            values=[profile.name for profile in self.profiles],
            state="readonly",
        )
        self.profile_combo.grid(row=3, column=1, sticky="ew", padx=8, pady=5)
        self.profile_combo.bind("<<ComboboxSelected>>", self._select_profile)
        ttk.Button(files, text="Manage…", command=self._manage_profiles).grid(
            row=3, column=2, pady=5
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=14)
        self.validate_button = ttk.Button(
            actions, text="Validate files", command=self._start_validation
        )
        self.process_button = ttk.Button(
            actions, text="Process balances", command=self._start_processing
        )
        self.preview_button = ttk.Button(
            actions, text="Preview profile", command=self._show_preview
        )
        self.validate_button.grid(row=0, column=0, sticky="ew")
        self.process_button.grid(row=0, column=1, sticky="ew", padx=8)
        self.preview_button.grid(row=0, column=2, sticky="ew")
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        results = ttk.LabelFrame(outer, text="Status and results", padding=14)
        results.pack(fill="both", expand=True)
        ttk.Label(results, textvariable=self.status_text, font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            results,
            textvariable=self.details_text,
            justify="left",
            wraplength=680,
        ).pack(anchor="w", pady=(10, 14))

        result_actions = ttk.Frame(results)
        result_actions.pack(fill="x")
        self.open_folder_button = ttk.Button(
            result_actions,
            text="Open results folder",
            command=lambda: self._open_result("folder"),
        )
        self.open_transfer_button = ttk.Button(
            result_actions,
            text="Open transfer CSV",
            command=lambda: self._open_result("transfer"),
        )
        self.open_review_button = ttk.Button(
            result_actions,
            text="Open manual review CSV",
            command=lambda: self._open_result("review"),
        )
        self.open_audit_button = ttk.Button(
            result_actions,
            text="Open match audit",
            command=lambda: self._open_result("audit"),
        )
        self.open_audit_control_button = ttk.Button(
            result_actions,
            text="Open audit control",
            command=lambda: self._open_result("audit_control"),
        )
        self.open_run_summary_button = ttk.Button(
            result_actions,
            text="Open run summary",
            command=lambda: self._open_result("run_summary"),
        )
        for index, button in enumerate(
            [
                self.open_folder_button,
                self.open_transfer_button,
                self.open_review_button,
                self.open_audit_button,
                self.open_audit_control_button,
                self.open_run_summary_button,
            ]
        ):
            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 8, 0),
                pady=(0 if index < 2 else 8, 0),
            )
        result_actions.columnconfigure(0, weight=1)
        result_actions.columnconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="Source files are never changed. Results are saved in a new timestamped folder.",
            foreground="#555555",
        ).pack(anchor="w", pady=(14, 0))
        self._build_manual_reconciliation_tab(manual_reconciliation_tab)
        self._build_initial_balances_tab(initial_balances_tab)

    def _build_manual_reconciliation_tab(self, parent: ttk.Frame) -> None:
        scroller = ScrollableFrame(parent, padding=22)
        scroller.pack(fill="both", expand=True)
        outer = scroller.content
        ttk.Label(
            outer,
            text="Manual Reconciliation Review",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Compare the original automated transfer with a manually reconciled copy "
                "before using it for InitialBalances."
            ),
        ).pack(anchor="w", pady=(3, 20))

        files = ttk.LabelFrame(outer, text="Review files", padding=14)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        self._file_row(
            files,
            0,
            "Original transfer",
            self.manual_original_text,
            self._choose_manual_original,
        )
        self._file_row(
            files,
            1,
            "Edited transfer",
            self.manual_edited_text,
            self._choose_manual_edited,
        )
        self._file_row(
            files,
            2,
            "Save results in",
            self.output_text,
            self._choose_output,
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=14)
        self.manual_review_button = ttk.Button(
            actions,
            text="Review edited transfer",
            command=self._start_manual_review,
        )
        self.manual_review_button.grid(row=0, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.manual_progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.manual_progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        results = ttk.LabelFrame(outer, text="Status and results", padding=14)
        results.pack(fill="both", expand=True)
        ttk.Label(
            results,
            textvariable=self.manual_status_text,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            results,
            textvariable=self.manual_details_text,
            justify="left",
            wraplength=680,
        ).pack(anchor="w", pady=(10, 14))
        result_actions = ttk.Frame(results)
        result_actions.pack(fill="x")
        self.manual_open_folder_button = ttk.Button(
            result_actions,
            text="Open results folder",
            command=lambda: self._open_manual_result("folder"),
        )
        self.manual_open_delta_button = ttk.Button(
            result_actions,
            text="Open delta audit",
            command=lambda: self._open_manual_result("delta"),
        )
        self.manual_open_summary_button = ttk.Button(
            result_actions,
            text="Open summary",
            command=lambda: self._open_manual_result("summary"),
        )
        for index, button in enumerate(
            [
                self.manual_open_folder_button,
                self.manual_open_delta_button,
                self.manual_open_summary_button,
            ]
        ):
            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 8, 0),
                pady=(0 if index < 2 else 8, 0),
            )
        result_actions.columnconfigure(0, weight=1)
        result_actions.columnconfigure(1, weight=1)
        ttk.Label(
            outer,
            text=(
                "Manual resolutions are expected. Changed automated balances, identity "
                "fields, and family codes are highlighted for audit review."
            ),
            foreground="#555555",
        ).pack(anchor="w", pady=(14, 0))

    def _build_initial_balances_tab(self, parent: ttk.Frame) -> None:
        scroller = ScrollableFrame(parent, padding=22)
        scroller.pack(fill="both", expand=True)
        outer = scroller.content
        ttk.Label(
            outer,
            text="InitialBalances Transfer",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Aggregate reconciled Odin balances by family code and add them to a "
                "Lunchtab InitialBalances export."
            ),
        ).pack(anchor="w", pady=(3, 20))

        files = ttk.LabelFrame(outer, text="Source files", padding=14)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        self._file_row(
            files,
            0,
            "Reconciled transfer",
            self.initial_transfer_text,
            self._choose_initial_transfer,
        )
        self._file_row(
            files,
            1,
            "InitialBalances",
            self.initial_balances_text,
            self._choose_initial_balances,
        )
        self._file_row(
            files,
            2,
            "Save results in",
            self.output_text,
            self._choose_output,
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=14)
        self.initial_validate_button = ttk.Button(
            actions,
            text="Validate files",
            command=self._start_initial_validation,
        )
        self.initial_process_button = ttk.Button(
            actions,
            text="Transfer and audit",
            command=self._start_initial_processing,
        )
        self.initial_validate_button.grid(row=0, column=0, sticky="ew")
        self.initial_process_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.initial_progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.initial_progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        results = ttk.LabelFrame(outer, text="Status and results", padding=14)
        results.pack(fill="both", expand=True)
        ttk.Label(
            results,
            textvariable=self.initial_status_text,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            results,
            textvariable=self.initial_details_text,
            justify="left",
            wraplength=680,
        ).pack(anchor="w", pady=(10, 14))
        result_actions = ttk.Frame(results)
        result_actions.pack(fill="x")
        self.initial_open_folder_button = ttk.Button(
            result_actions,
            text="Open results folder",
            command=lambda: self._open_initial_result("folder"),
        )
        self.initial_open_processed_button = ttk.Button(
            result_actions,
            text="Open processed CSV",
            command=lambda: self._open_initial_result("processed"),
        )
        self.initial_open_audit_button = ttk.Button(
            result_actions,
            text="Open transfer audit",
            command=lambda: self._open_initial_result("audit"),
        )
        self.initial_open_exceptions_button = ttk.Button(
            result_actions,
            text="Open exceptions",
            command=lambda: self._open_initial_result("exceptions"),
        )
        self.initial_open_audit_control_button = ttk.Button(
            result_actions,
            text="Open audit control",
            command=lambda: self._open_initial_result("audit_control"),
        )
        self.initial_open_run_summary_button = ttk.Button(
            result_actions,
            text="Open run summary",
            command=lambda: self._open_initial_result("run_summary"),
        )
        for index, button in enumerate(
            [
                self.initial_open_folder_button,
                self.initial_open_processed_button,
                self.initial_open_audit_button,
                self.initial_open_exceptions_button,
                self.initial_open_audit_control_button,
                self.initial_open_run_summary_button,
            ]
        ):
            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 8, 0),
                pady=(0 if index < 2 else 8, 0),
            )
        result_actions.columnconfigure(0, weight=1)
        result_actions.columnconfigure(1, weight=1)
        ttk.Label(
            outer,
            text=(
                "Source files are never changed. Any integrity exception blocks the "
                "processed import while preserving audit reports."
            ),
            foreground="#555555",
        ).pack(anchor="w", pady=(14, 0))

    @staticmethod
    def _file_row(
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, state="readonly").grid(
            row=row, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(parent, text="Browse…", command=command).grid(row=row, column=2, pady=5)

    def _choose_odin(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Odin account balance report",
            filetypes=[("Excel workbooks", "*.xlsx")],
        )
        if selected:
            self.odin_text.set(selected)
            self.controller.select_odin(Path(selected))
            self._render()

    def _choose_lunchtab(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Lunchtab users export",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.lunchtab_text.set(selected)
            self.controller.select_lunchtab(Path(selected))
            self._render()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose the parent folder for timestamped results")
        if selected:
            self.output_text.set(selected)
            self.controller.select_output_root(Path(selected))
            self.initial_controller.select_output_root(Path(selected))
            self.manual_controller.select_output_root(Path(selected))
            self._render()

    def _choose_manual_original(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select original automated transfer CSV",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.manual_original_text.set(selected)
            self.manual_controller.select_original_transfer(Path(selected))
            self._render()

    def _choose_manual_edited(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select manually reconciled transfer CSV",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.manual_edited_text.set(selected)
            self.manual_controller.select_edited_transfer(Path(selected))
            self._render()

    def _choose_initial_transfer(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select reconciled Odin-to-Lunchtab transfer",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.initial_transfer_text.set(selected)
            self.initial_controller.select_transfer(Path(selected))
            self._render()

    def _choose_initial_balances(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Lunchtab InitialBalances export",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.initial_balances_text.set(selected)
            self.initial_controller.select_initial_balances(Path(selected))
            self._render()

    def _select_profile(self, _: object | None = None) -> None:
        selected = next(
            profile for profile in self.profiles if profile.name == self.profile_text.get()
        )
        self.preview = None
        self.controller.select_profile(selected)
        self._render()

    def _manage_profiles(self) -> None:
        state = self.controller.state
        source_paths = (
            (state.odin_path, state.lunchtab_path)
            if state.odin_path and state.lunchtab_path
            else None
        )
        manager = ProfileManager(
            self.root,
            state.inspection.account_types if state.inspection else (),
            state.inspection.email_domains if state.inspection else (),
            source_paths,
        )
        self.root.wait_window(manager)
        self.profiles = list_profiles()
        self.profile_combo.configure(values=[profile.name for profile in self.profiles])
        if self.profile_text.get() not in {profile.name for profile in self.profiles}:
            self.profile_text.set(self.profiles[0].name)
            self._select_profile()

    def _run_worker(
        self,
        event_name: str,
        operation: Callable[[], object],
        error_event: str = "error",
    ) -> None:
        def work() -> None:
            try:
                self.events.put((event_name, operation()))
            except Exception as error:
                self.logger.exception("%s failed: %s", event_name, type(error).__name__)
                self.events.put((error_event, error))

        threading.Thread(target=work, daemon=True).start()

    def _start_validation(self) -> None:
        state = self.controller.begin_validation()
        self._render()
        self._run_worker(
            "validated",
            lambda: (
                inspect_inputs(  # type: ignore[arg-type]
                    state.odin_path,
                    state.lunchtab_path,
                    state.profile,
                ),
                preview_profile(
                    state.odin_path,  # type: ignore[arg-type]
                    state.lunchtab_path,  # type: ignore[arg-type]
                    state.profile,
                ),
            ),
        )

    def _start_processing(self) -> None:
        state = self.controller.begin_processing()
        self._render()
        self._run_worker(
            "processed",
            lambda: run_managed_workflow(
                odin_path=state.odin_path,  # type: ignore[arg-type]
                lunchtab_path=state.lunchtab_path,  # type: ignore[arg-type]
                output_root=state.output_root,
                profile=state.profile,
            ),
        )

    def _start_initial_validation(self) -> None:
        state = self.initial_controller.begin_validation()
        self._render()
        self._run_worker(
            "initial_validated",
            lambda: (
                inspect_initial_balances_inputs(
                    state.transfer_path,  # type: ignore[arg-type]
                    state.initial_balances_path,  # type: ignore[arg-type]
                ),
                preflight_initial_balances_transfer(
                    state.transfer_path,  # type: ignore[arg-type]
                    state.initial_balances_path,  # type: ignore[arg-type]
                ),
            ),
            "initial_error",
        )

    def _start_initial_processing(self) -> None:
        state = self.initial_controller.begin_processing()
        self._render()
        self._run_worker(
            "initial_processed",
            lambda: run_initial_balances_workflow(
                transfer_path=state.transfer_path,  # type: ignore[arg-type]
                initial_balances_path=state.initial_balances_path,  # type: ignore[arg-type]
                output_root=state.output_root,  # type: ignore[arg-type]
            ),
            "initial_error",
        )

    def _start_manual_review(self) -> None:
        state = self.manual_controller.begin_review()
        self._render()
        self._run_worker(
            "manual_reviewed",
            lambda: run_manual_reconciliation_workflow(
                original_transfer_path=state.original_transfer_path,  # type: ignore[arg-type]
                edited_transfer_path=state.edited_transfer_path,  # type: ignore[arg-type]
                output_root=state.output_root,  # type: ignore[arg-type]
            ),
            "manual_error",
        )

    def _show_preview(self) -> None:
        if self.preview is None:
            messagebox.showinfo(
                APP_TITLE,
                "Validate the selected files and profile before viewing a dry-run preview.",
            )
            return
        PreviewWindow(self.root, self.preview)

    def _poll_events(self) -> None:
        try:
            while True:
                name, payload = self.events.get_nowait()
                if name == "validated":
                    inspection, self.preview = payload  # type: ignore[misc]
                    self.controller.validation_succeeded(inspection)
                elif name == "processed":
                    self.controller.processing_succeeded(payload)  # type: ignore[arg-type]
                    result = self.controller.state.result
                    self.logger.info(
                        "Transfer completed: matched_id=%s matched_name=%s exceptions=%s",
                        result.summary.matched_by_id,
                        result.summary.matched_by_name,
                        result.summary.exceptions,
                    )
                elif name == "initial_validated":
                    inspection, preflight = payload  # type: ignore[misc]
                    self.initial_controller.validation_succeeded(inspection, preflight)
                elif name == "initial_processed":
                    self.initial_controller.processing_succeeded(payload)  # type: ignore[arg-type]
                    result = self.initial_controller.state.result
                    self.logger.info(
                        "InitialBalances run completed: blocked=%s updated_families=%s "
                        "exceptions=%s",
                        result.summary.blocked,
                        result.summary.updated_families,
                        result.summary.exceptions,
                    )
                    if result.summary.blocked:
                        messagebox.showwarning(
                            APP_TITLE,
                            "The processed import was blocked. Open the exception and audit "
                            "reports, reconcile the source CSV, and run the transfer again.",
                        )
                    else:
                        messagebox.showinfo(
                            APP_TITLE,
                            "InitialBalances transfer and integrity audit completed successfully.",
                        )
                elif name == "manual_reviewed":
                    self.manual_controller.review_succeeded(payload)  # type: ignore[arg-type]
                    result = self.manual_controller.state.result
                    self.logger.info(
                        "Manual reconciliation review completed: status=%s manual=%s "
                        "high_risk_balance=%s invalid=%s",
                        result.summary.status,
                        result.summary.manual_resolutions,
                        result.summary.changed_automated_balances
                        + result.summary.cleared_automated_balances,
                        result.summary.invalid_manual_amounts,
                    )
                    if result.summary.status == "BLOCKED":
                        messagebox.showwarning(
                            APP_TITLE,
                            "The edited transfer has invalid balances. Open the delta audit, "
                            "fix the edited CSV, and run the review again.",
                        )
                    elif result.summary.status == "REVIEW":
                        messagebox.showinfo(
                            APP_TITLE,
                            "Manual reconciliation review completed with high-risk edits. "
                            "Open the delta audit before using the edited transfer.",
                        )
                elif name == "initial_error":
                    self.initial_controller.failed(friendly_error(payload))  # type: ignore[arg-type]
                elif name == "manual_error":
                    self.manual_controller.failed(friendly_error(payload))  # type: ignore[arg-type]
                else:
                    self.controller.failed(friendly_error(payload))  # type: ignore[arg-type]
                self._render()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _open_initial_result(self, target: str) -> None:
        result = self.initial_controller.state.result
        if result is None:
            return
        targets = {
            "folder": result.run_dir,
            "processed": result.summary.output_paths.processed,
            "audit": result.summary.output_paths.audit,
            "exceptions": result.summary.output_paths.exceptions,
            "audit_control": result.summary.output_paths.audit_control,
            "run_summary": result.summary.output_paths.run_summary,
        }
        try:
            path = targets[target]
            if path is not None:
                open_path(path)
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _open_manual_result(self, target: str) -> None:
        result = self.manual_controller.state.result
        if result is None:
            return
        targets = {
            "folder": result.run_dir,
            "delta": result.summary.output_paths.delta_audit,
            "summary": result.summary.output_paths.summary,
        }
        try:
            open_path(targets[target])
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _open_result(self, target: str) -> None:
        result = self.controller.state.result
        if result is None:
            return
        targets = {
            "folder": result.run_dir,
            "transfer": result.summary.output_paths.transfer,
            "review": result.summary.output_paths.manual_review_exceptions,
            "audit": result.summary.output_paths.match_audit,
            "audit_control": result.summary.output_paths.audit_control,
            "run_summary": result.summary.output_paths.run_summary,
        }
        try:
            path = targets[target]
            if path is not None:
                open_path(path)
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _render(self) -> None:
        state = self.controller.state
        busy = state.phase in {AppPhase.VALIDATING, AppPhase.PROCESSING}
        self.validate_button.configure(state="normal" if state.can_validate else "disabled")
        self.process_button.configure(state="normal" if state.can_process else "disabled")
        self.preview_button.configure(state="normal" if self.preview else "disabled")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        self.status_text.set(state.message)
        wrap_width = max(400, self.root.winfo_width() - 140)
        for child in self.root.winfo_children():
            self._update_wraplength(child, wrap_width)

        if state.result:
            summary = state.result.summary
            warning = (
                f"\n\nAttention: {summary.manual_review_exceptions} record(s) require manual review."
                if summary.manual_review_exceptions
                else "\n\nNo records require manual review."
            )
            self.details_text.set(
                f"Matched by ID: {summary.matched_by_id}\n"
                f"Matched by name: {summary.matched_by_name}\n"
                f"Matching profile: {summary.profile_name}\n"
                f"All exceptions: {summary.exceptions}\n"
                f"Malformed Odin rows: {summary.malformed}\n"
                f"Audit-control status: {summary.audit_control_status}\n"
                f"Lunchtab output rows: {summary.lunchtab_rows}"
                f"{warning}\n\nSaved to: {state.result.run_dir}"
            )
        elif state.inspection:
            inspection = state.inspection
            self.details_text.set(
                f"Valid Odin rows: {inspection.odin_rows}\n"
                f"Malformed Odin rows: {inspection.malformed_odin_rows}\n"
                f"Lunchtab rows: {inspection.lunchtab_rows}"
            )
        else:
            self.details_text.set("")

        result_state = "normal" if state.result else "disabled"
        self.open_folder_button.configure(state=result_state)
        self.open_transfer_button.configure(state=result_state)
        self.open_review_button.configure(state=result_state)
        self.open_audit_button.configure(state=result_state)
        self.open_audit_control_button.configure(state=result_state)
        self.open_run_summary_button.configure(state=result_state)

        manual_state = self.manual_controller.state
        manual_busy = manual_state.phase == ManualReconciliationPhase.REVIEWING
        self.manual_review_button.configure(
            state="normal" if manual_state.can_review else "disabled"
        )
        if manual_busy:
            self.manual_progress.start(10)
        else:
            self.manual_progress.stop()
        self.manual_status_text.set(manual_state.message)
        if manual_state.result:
            summary = manual_state.result.summary
            self.manual_details_text.set(
                f"Review status: {summary.status}\n"
                f"Original transfer rows: {summary.original_rows}\n"
                f"Edited transfer rows: {summary.edited_rows}\n"
                f"Unchanged automated matches: {summary.unchanged_automated_matches}\n"
                f"Manual resolutions: {summary.manual_resolutions}\n"
                f"Changed automated balances: {summary.changed_automated_balances}\n"
                f"Cleared automated balances: {summary.cleared_automated_balances}\n"
                f"Invalid manual amounts: {summary.invalid_manual_amounts}\n"
                f"Family-code changes: {summary.family_code_changes}\n"
                f"Identity-field changes: {summary.identity_field_changes}\n"
                f"Other field changes: {summary.other_field_changes}\n\n"
                f"Saved to: {manual_state.result.run_dir}"
            )
        else:
            self.manual_details_text.set("")
        manual_result_state = "normal" if manual_state.result else "disabled"
        self.manual_open_folder_button.configure(state=manual_result_state)
        self.manual_open_delta_button.configure(state=manual_result_state)
        self.manual_open_summary_button.configure(state=manual_result_state)

        initial_state = self.initial_controller.state
        initial_busy = initial_state.phase in {
            InitialBalancesPhase.VALIDATING,
            InitialBalancesPhase.PROCESSING,
        }
        self.initial_validate_button.configure(
            state="normal" if initial_state.can_validate else "disabled"
        )
        self.initial_process_button.configure(
            state="normal" if initial_state.can_process else "disabled"
        )
        if initial_busy:
            self.initial_progress.start(10)
        else:
            self.initial_progress.stop()
        self.initial_status_text.set(initial_state.message)
        if initial_state.result:
            summary = initial_state.result.summary
            blocked = (
                "\n\nProcessed import: BLOCKED"
                if summary.blocked
                else "\n\nProcessed import: ready"
            )
            self.initial_details_text.set(
                f"Populated transfer rows: {summary.populated_balance_rows}\n"
                f"Matched source rows: {summary.matched_source_rows}\n"
                f"Updated families: {summary.updated_families}\n"
                f"Exceptions: {summary.exceptions}\n"
                f"Audit-control status: {summary.audit_control_status}\n"
                f"Applied total: {summary.applied_total}"
                f"{blocked}\n\nSaved to: {initial_state.result.run_dir}"
            )
        elif initial_state.inspection:
            inspection = initial_state.inspection
            if initial_state.preflight:
                preflight = initial_state.preflight
                status = "BLOCKED" if preflight.blocked else "READY"
                reasons = (
                    "\n".join(
                        f"  - {reason}: {count}"
                        for reason, count in preflight.exception_reasons.items()
                    )
                    or "  - None"
                )
                self.initial_details_text.set(
                    f"Preflight result: {status}\n"
                    f"Transfer rows: {preflight.transfer_rows}\n"
                    f"Populated balance rows: {preflight.populated_balance_rows}\n"
                    f"Matched source rows: {preflight.matched_source_rows}\n"
                    f"Updated families: {preflight.updated_families}\n"
                    f"Exceptions: {preflight.exceptions}\n"
                    f"Applied total if run: {preflight.applied_total}\n"
                    f"Blocked total if run: {preflight.blocked_total}\n"
                    f"Exception reasons:\n{reasons}"
                )
            else:
                self.initial_details_text.set(
                    f"Transfer rows: {inspection.transfer_rows}\n"
                    f"Populated balance rows: {inspection.populated_balance_rows}\n"
                    f"InitialBalances rows: {inspection.initial_balance_rows}"
                )
        else:
            self.initial_details_text.set("")
        initial_result_state = "normal" if initial_state.result else "disabled"
        self.initial_open_folder_button.configure(state=initial_result_state)
        self.initial_open_audit_button.configure(state=initial_result_state)
        self.initial_open_exceptions_button.configure(state=initial_result_state)
        self.initial_open_audit_control_button.configure(state=initial_result_state)
        self.initial_open_run_summary_button.configure(state=initial_result_state)
        self.initial_open_processed_button.configure(
            state=(
                "normal"
                if initial_state.result
                and initial_state.result.summary.output_paths.processed is not None
                else "disabled"
            )
        )

    def _update_wraplength(self, widget: tk.Misc, width: int) -> None:
        try:
            if isinstance(widget, ttk.Label):
                widget.configure(wraplength=width)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._update_wraplength(child, width)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", action="store_true")
    return parser


def main() -> None:
    args, _ = build_parser().parse_known_args()
    if args.smoke_test:
        configure_logging()
        return
    root = tk.Tk()
    BalanceTransferApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
