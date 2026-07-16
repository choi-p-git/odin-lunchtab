from __future__ import annotations

import argparse
import queue
import random
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from odin_lunchtab.app_logging import configure_logging
from odin_lunchtab.desktop import friendly_error, open_path
from odin_lunchtab.sandbox_controller import SandboxController, SandboxPhase
from odin_lunchtab.sandbox_data import (
    BalanceConfig,
    IdentifierConvention,
    PRESET_NAMES,
    SandboxConfig,
    SandboxExceptionCounts,
    SandboxVerificationResult,
    generate_and_verify_sandbox_pack,
    generate_sandbox_pack,
    preset_config,
)
from odin_lunchtab.ui_helpers import ScrollableFrame, size_and_center

APP_TITLE = "Odin Lunchtab Sandbox Data Generator"


class SandboxApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.logger = configure_logging()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.controller = SandboxController(preset_config("Clean baseline"))

        root.title(APP_TITLE)
        size_and_center(root, 920, 760)

        config = self.controller.state.config
        self.preset_text = tk.StringVar(value=config.preset)
        self.output_text = tk.StringVar(value=str(config.output_root))
        self.seed_text = tk.StringVar(value=str(config.seed))
        self.total_odin_text = tk.StringVar(value=str(config.total_odin_rows))
        self.total_lunchtab_text = tk.StringVar(value=str(config.total_lunchtab_rows))
        self.matchable_text = tk.StringVar(value=str(config.matchable_rows))
        self.odin_prefix_text = tk.StringVar(value=config.odin_id.prefix)
        self.odin_start_text = tk.StringVar(value=str(config.odin_id.start))
        self.odin_pad_text = tk.StringVar(value=str(config.odin_id.zero_pad))
        self.barcode_prefix_text = tk.StringVar(value=config.lunchtab_barcode.prefix)
        self.barcode_start_text = tk.StringVar(value=str(config.lunchtab_barcode.start))
        self.barcode_pad_text = tk.StringVar(value=str(config.lunchtab_barcode.zero_pad))
        self.family_prefix_text = tk.StringVar(value=config.family_code.prefix)
        self.family_start_text = tk.StringVar(value=str(config.family_code.start))
        self.family_pad_text = tk.StringVar(value=str(config.family_code.zero_pad))
        self.family_grouping_text = tk.StringVar(value=config.family_grouping)
        self.shared_family_size_text = tk.StringVar(value=str(config.shared_family_size))
        self.min_balance_text = tk.StringVar(value=config.balance.minimum)
        self.max_balance_text = tk.StringVar(value=config.balance.maximum)
        self.balance_mode_text = tk.StringVar(value=config.balance.mode)
        self.status_text = tk.StringVar(value=self.controller.state.message)
        self.details_text = tk.StringVar(value="")
        self.exception_vars: dict[str, tk.StringVar] = {}

        self._build()
        self._set_exception_vars(config.exceptions)
        self._render()
        root.after(100, self._poll_events)

    def _build(self) -> None:
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        scroller = ScrollableFrame(self.root, padding=22)
        scroller.grid(row=0, column=0, sticky="nsew")
        outer = scroller.content

        ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Create deterministic non-live Odin and LunchTab source files.",
        ).pack(anchor="w", pady=(3, 18))

        scenario = ttk.LabelFrame(outer, text="Scenario", padding=14)
        scenario.pack(fill="x")
        scenario.columnconfigure(1, weight=1)
        self._combo_row(
            scenario,
            0,
            "Preset",
            self.preset_text,
            list(PRESET_NAMES),
            self._select_preset,
        )
        self._entry_row(scenario, 1, "Output folder", self.output_text, self._choose_output)
        self._entry_row(scenario, 2, "Seed", self.seed_text, self._randomize_seed)

        rows = ttk.LabelFrame(outer, text="Rows", padding=14)
        rows.pack(fill="x", pady=(12, 0))
        for column in range(3):
            rows.columnconfigure(column * 2 + 1, weight=1)
        self._compact_entry(rows, 0, 0, "Odin rows", self.total_odin_text)
        self._compact_entry(rows, 0, 2, "LunchTab rows", self.total_lunchtab_text)
        self._compact_entry(rows, 0, 4, "Matchable rows", self.matchable_text)

        conventions = ttk.LabelFrame(outer, text="Conventions", padding=14)
        conventions.pack(fill="x", pady=(12, 0))
        for column in range(3):
            conventions.columnconfigure(column * 2 + 1, weight=1)
        self._compact_entry(conventions, 0, 0, "Odin prefix", self.odin_prefix_text)
        self._compact_entry(conventions, 0, 2, "Odin start", self.odin_start_text)
        self._compact_entry(conventions, 0, 4, "Odin pad", self.odin_pad_text)
        self._compact_entry(conventions, 1, 0, "Barcode prefix", self.barcode_prefix_text)
        self._compact_entry(conventions, 1, 2, "Barcode start", self.barcode_start_text)
        self._compact_entry(conventions, 1, 4, "Barcode pad", self.barcode_pad_text)
        self._compact_entry(conventions, 2, 0, "Family prefix", self.family_prefix_text)
        self._compact_entry(conventions, 2, 2, "Family start", self.family_start_text)
        self._compact_entry(conventions, 2, 4, "Family pad", self.family_pad_text)
        self._compact_entry(conventions, 3, 0, "Shared size", self.shared_family_size_text)
        ttk.Label(conventions, text="Family mode").grid(row=3, column=2, sticky="w", pady=5)
        family_mode = ttk.Combobox(
            conventions,
            textvariable=self.family_grouping_text,
            values=["one_per_family", "shared_every_n", "mixed"],
            state="readonly",
        )
        family_mode.grid(row=3, column=3, columnspan=3, sticky="ew", padx=8, pady=5)

        balances = ttk.LabelFrame(outer, text="Balances", padding=14)
        balances.pack(fill="x", pady=(12, 0))
        for column in range(3):
            balances.columnconfigure(column * 2 + 1, weight=1)
        self._compact_entry(balances, 0, 0, "Minimum", self.min_balance_text)
        self._compact_entry(balances, 0, 2, "Maximum", self.max_balance_text)
        ttk.Label(balances, text="Mode").grid(row=0, column=4, sticky="w", pady=5)
        ttk.Combobox(
            balances,
            textvariable=self.balance_mode_text,
            values=["positive", "positive_negative_zero"],
            state="readonly",
        ).grid(row=0, column=5, sticky="ew", padx=8, pady=5)

        exceptions = ttk.LabelFrame(outer, text="Exception counts", padding=14)
        exceptions.pack(fill="x", pady=(12, 0))
        for column in range(2):
            exceptions.columnconfigure(column * 2 + 1, weight=1)
        for index, (field, label) in enumerate(_EXCEPTION_FIELDS):
            var = tk.StringVar(value="0")
            self.exception_vars[field] = var
            self._compact_entry(exceptions, index // 2, (index % 2) * 2, label, var)

        results = ttk.LabelFrame(outer, text="Status and results", padding=14)
        results.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(results, textvariable=self.status_text, font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        ttk.Label(results, textvariable=self.details_text, justify="left", wraplength=760).pack(
            anchor="w",
            pady=(10, 0),
        )

        actions = ttk.Frame(self.root, padding=(22, 10))
        actions.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        self.generate_button = ttk.Button(
            actions,
            text="Generate",
            command=lambda: self._start_generation(False),
        )
        self.verify_button = ttk.Button(
            actions,
            text="Generate + Verify",
            command=lambda: self._start_generation(True),
        )
        self.open_button = ttk.Button(actions, text="Open output folder", command=self._open_output)
        self.generate_button.grid(row=0, column=0, sticky="ew")
        self.verify_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.open_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=3, sticky="ew", padx=(8, 0))

    @staticmethod
    def _entry_row(
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(
            parent, text="Browse..." if label == "Output folder" else "Randomize", command=command
        ).grid(
            row=row,
            column=2,
            pady=5,
        )

    @staticmethod
    def _combo_row(
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        values: list[str],
        callback: Callable[[object | None], None],
    ) -> None:
        ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w", pady=5)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", padx=8, pady=5)
        combo.bind("<<ComboboxSelected>>", callback)

    @staticmethod
    def _compact_entry(
        parent: ttk.LabelFrame,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, width=12).grid(
            row=row,
            column=column + 1,
            sticky="ew",
            padx=8,
            pady=5,
        )

    def _select_preset(self, _: object | None = None) -> None:
        config = preset_config(self.preset_text.get(), output_root=Path(self.output_text.get()))
        self._load_config(config)
        self._update_controller_config()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Choose sandbox output folder")
        if selected:
            self.output_text.set(selected)
            self._update_controller_config()

    def _randomize_seed(self) -> None:
        self.seed_text.set(str(random.randint(1, 999999999)))
        self._update_controller_config()

    def _load_config(self, config: SandboxConfig) -> None:
        self.preset_text.set(config.preset)
        self.seed_text.set(str(config.seed))
        self.total_odin_text.set(str(config.total_odin_rows))
        self.total_lunchtab_text.set(str(config.total_lunchtab_rows))
        self.matchable_text.set(str(config.matchable_rows))
        self.odin_prefix_text.set(config.odin_id.prefix)
        self.odin_start_text.set(str(config.odin_id.start))
        self.odin_pad_text.set(str(config.odin_id.zero_pad))
        self.barcode_prefix_text.set(config.lunchtab_barcode.prefix)
        self.barcode_start_text.set(str(config.lunchtab_barcode.start))
        self.barcode_pad_text.set(str(config.lunchtab_barcode.zero_pad))
        self.family_prefix_text.set(config.family_code.prefix)
        self.family_start_text.set(str(config.family_code.start))
        self.family_pad_text.set(str(config.family_code.zero_pad))
        self.family_grouping_text.set(config.family_grouping)
        self.shared_family_size_text.set(str(config.shared_family_size))
        self.min_balance_text.set(config.balance.minimum)
        self.max_balance_text.set(config.balance.maximum)
        self.balance_mode_text.set(config.balance.mode)
        self._set_exception_vars(config.exceptions)

    def _set_exception_vars(self, counts: SandboxExceptionCounts) -> None:
        for field, _ in _EXCEPTION_FIELDS:
            if field in self.exception_vars:
                self.exception_vars[field].set(str(getattr(counts, field)))

    def _config_from_form(self) -> SandboxConfig:
        odin_id = IdentifierConvention(
            prefix=self.odin_prefix_text.get(),
            start=int(self.odin_start_text.get()),
            zero_pad=int(self.odin_pad_text.get()),
        )
        barcode = IdentifierConvention(
            prefix=self.barcode_prefix_text.get(),
            start=int(self.barcode_start_text.get()),
            zero_pad=int(self.barcode_pad_text.get()),
        )
        family = IdentifierConvention(
            prefix=self.family_prefix_text.get(),
            start=int(self.family_start_text.get()),
            zero_pad=int(self.family_pad_text.get()),
        )
        exceptions = SandboxExceptionCounts(
            **{field: int(variable.get()) for field, variable in self.exception_vars.items()}
        )
        return SandboxConfig(
            preset=self.preset_text.get(),
            total_odin_rows=int(self.total_odin_text.get()),
            total_lunchtab_rows=int(self.total_lunchtab_text.get()),
            matchable_rows=int(self.matchable_text.get()),
            odin_id=odin_id,
            lunchtab_barcode=barcode,
            family_code=family,
            family_grouping=self.family_grouping_text.get(),  # type: ignore[arg-type]
            shared_family_size=int(self.shared_family_size_text.get()),
            balance=BalanceConfig(
                minimum=self.min_balance_text.get(),
                maximum=self.max_balance_text.get(),
                mode=self.balance_mode_text.get(),  # type: ignore[arg-type]
            ),
            seed=int(self.seed_text.get()),
            output_root=Path(self.output_text.get()),
            exceptions=exceptions,
        )

    def _update_controller_config(self) -> bool:
        try:
            self.controller.update_config(self._config_from_form())
        except Exception as error:
            self.controller.failed(friendly_error(error))
            self._render()
            return False
        self._render()
        return True

    def _start_generation(self, verify: bool) -> None:
        if not self._update_controller_config():
            return
        state = self.controller.begin_generation(verify=verify)
        self._render()

        def operation() -> SandboxVerificationResult:
            if verify:
                return generate_and_verify_sandbox_pack(state.config)
            pack = generate_sandbox_pack(state.config)
            return SandboxVerificationResult(pack=pack)

        self._run_worker("generated", operation)

    def _run_worker(self, event_name: str, operation: Callable[[], object]) -> None:
        def work() -> None:
            try:
                self.events.put((event_name, operation()))
            except Exception as error:
                self.logger.exception("Sandbox generation failed: %s", type(error).__name__)
                self.events.put(("error", error))

        threading.Thread(target=work, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                name, payload = self.events.get_nowait()
                if name == "generated":
                    self.controller.generation_succeeded(payload)  # type: ignore[arg-type]
                else:
                    self.controller.failed(friendly_error(payload))  # type: ignore[arg-type]
                self._render()
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _open_output(self) -> None:
        folder = self.controller.state.output_folder
        if folder is None:
            return
        try:
            open_path(folder)
        except Exception as error:
            messagebox.showerror(APP_TITLE, friendly_error(error))

    def _render(self) -> None:
        state = self.controller.state
        busy = state.phase == SandboxPhase.GENERATING
        self.generate_button.configure(state="disabled" if busy else "normal")
        self.verify_button.configure(state="disabled" if busy else "normal")
        self.open_button.configure(state="normal" if state.output_folder else "disabled")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        self.status_text.set(state.message)
        self.details_text.set(_details(state.result) if state.result else "")


def _details(result: SandboxVerificationResult | None) -> str:
    if result is None:
        return ""
    expected = result.pack.expected
    lines = [
        f"Odin rows: {expected.odin_rows}",
        f"LunchTab rows: {expected.lunchtab_rows}",
        f"InitialBalances rows: {expected.initial_balance_rows}",
        f"Expected matched rows: {expected.matched_rows}",
        f"Expected reconciliation exceptions: {expected.reconciliation_exceptions}",
        f"Expected manual review exceptions: {expected.manual_review_exceptions}",
        f"Expected InitialBalances blocked: {expected.initial_balances_blocked}",
        f"Saved to: {result.pack.run_dir}",
    ]
    if result.verification is not None:
        lines.extend(
            [
                "",
                f"Verification reconciliation passed: {result.verification.reconciliation_passed}",
                f"Verification InitialBalances passed: {result.verification.initial_balances_passed}",
            ]
        )
        if result.verification.mismatches:
            lines.append("Mismatches:")
            lines.extend(result.verification.mismatches)
    return "\n".join(lines)


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
    SandboxApp(root)
    root.mainloop()


_EXCEPTION_FIELDS = [
    ("unmatched_odin", "Unmatched Odin"),
    ("duplicate_odin_id_pairs", "Duplicate Odin pairs"),
    ("duplicate_lunchtab_identifier", "Duplicate LT IDs"),
    ("name_validation_failures", "Name failures"),
    ("ambiguous_name_fallbacks", "Ambiguous names"),
    ("multiple_odin_to_one_lunchtab", "Many Odin to one LT"),
    ("malformed_missing_fields", "Missing Odin fields"),
    ("malformed_invalid_balances", "Invalid Odin balances"),
    ("blank_family_codes", "Blank family codes"),
    ("missing_initial_family_codes", "Missing Initial family"),
    ("duplicate_initial_family_codes", "Duplicate Initial family"),
    ("invalid_initial_amounts", "Invalid Initial amount"),
]


if __name__ == "__main__":
    main()
