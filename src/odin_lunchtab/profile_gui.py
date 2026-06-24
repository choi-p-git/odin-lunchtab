from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from odin_lunchtab.managed import ProfilePreview, preview_profile
from odin_lunchtab.profiles import (
    CrosswalkEntry,
    MatchingProfile,
    MatchingRule,
    TransformStep,
    delete_profile,
    duplicate_profile,
    export_crosswalk,
    export_profile,
    import_crosswalk,
    import_profile,
    list_profiles,
    save_profile,
    valid_email_domain,
)
from odin_lunchtab.ui_helpers import (
    ScrollableFrame,
    ToolTip,
    add_tree_scrollbars,
    responsive_button_grid,
    size_and_center,
)

TARGET_LABELS = {
    "LoginBarcode": "Login barcode",
    "ExternalId": "External ID",
    "EmailUsername": "Email username",
}
TARGET_VALUES = {label: value for value, label in TARGET_LABELS.items()}
TRANSFORM_LABELS = {
    "trim": "Trim whitespace",
    "add_prefix": "Add prefix",
    "remove_prefix": "Remove prefix",
    "add_suffix": "Add suffix",
    "remove_suffix": "Remove suffix",
    "zero_pad": "Zero-pad to width",
    "strip_leading_zeros": "Strip leading zeros",
    "substring": "Extract substring",
}
TRANSFORM_VALUES = {label: value for value, label in TRANSFORM_LABELS.items()}


def transform_label(step: TransformStep) -> str:
    label = TRANSFORM_LABELS[step.kind]
    if step.kind == "substring":
        return f"{label} [{step.start or ''}:{step.end or ''}]"
    return f"{label}: {step.value}" if step.value else label


class ChoiceChecklist(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        discovered: tuple[str, ...],
        selected: tuple[str, ...],
        *,
        allow_all: bool,
        all_selected: bool = False,
        input_hint: str = "",
        tooltip: str = "",
        normalize: Callable[[str], str] | None = None,
        validate: Callable[[str], bool] | None = None,
        invalid_message: str = "Enter a valid value.",
    ) -> None:
        super().__init__(parent, text=title, padding=8)
        self.allow_all = allow_all
        self.normalize = normalize or (lambda value: value.strip())
        self.validate = validate
        self.invalid_message = invalid_message
        self.all_var = tk.BooleanVar(value=all_selected)
        self.variables: dict[str, tk.BooleanVar] = {}
        self.checks = ttk.Frame(self)
        if allow_all:
            self.all_check = ttk.Checkbutton(
                self,
                text="All values",
                variable=self.all_var,
                command=self._toggle_all,
            )
            self.all_check.pack(anchor="w")
        self.checks.pack(fill="x", pady=(4, 6))
        combined = list(dict.fromkeys((*discovered, *selected)))
        for index, value in enumerate(combined):
            display = value if value in discovered else f"{value} (custom)"
            variable = tk.BooleanVar(value=value in selected)
            ttk.Checkbutton(self.checks, text=display, variable=variable).grid(
                row=index // 3, column=index % 3, sticky="w", padx=(0, 12), pady=2
            )
            self.variables[value] = variable
        custom_row = ttk.Frame(self)
        custom_row.pack(fill="x")
        self.custom_var = tk.StringVar()
        self.custom_entry = ttk.Entry(custom_row, textvariable=self.custom_var)
        self.custom_entry.pack(side="left", fill="x", expand=True)
        self.custom_entry.bind("<Return>", lambda _: self._add_custom())
        self.add_button = ttk.Button(custom_row, text="Add custom", command=self._add_custom)
        self.add_button.pack(side="left", padx=(6, 0))
        self.hint_var = tk.StringVar(value=input_hint)
        if input_hint:
            hint = ttk.Label(self, textvariable=self.hint_var, wraplength=620, justify="left")
            hint.pack(anchor="w", pady=(6, 0))
            if tooltip:
                self.hint_tooltip = ToolTip(hint, tooltip)
        if tooltip:
            self.entry_tooltip = ToolTip(self.custom_entry, tooltip)
        self.error_var = tk.StringVar()
        self.error_label = ttk.Label(
            self,
            textvariable=self.error_var,
            foreground="#b00020",
            wraplength=620,
            justify="left",
        )
        self.error_label.pack(anchor="w", pady=(3, 0))
        self._toggle_all()

    def _toggle_all(self) -> None:
        state = "disabled" if self.allow_all and self.all_var.get() else "normal"
        for child in self.checks.winfo_children():
            child.configure(state=state)

    def _add_custom(self) -> None:
        value = self.normalize(self.custom_var.get())
        if not value:
            return
        if self.validate is not None and not self.validate(value):
            self.error_var.set(self.invalid_message)
            return
        self.error_var.set("")
        if self.allow_all:
            self.all_var.set(False)
            self._toggle_all()
        if value in self.variables:
            self.variables[value].set(True)
        else:
            variable = tk.BooleanVar(value=True)
            index = len(self.variables)
            ttk.Checkbutton(
                self.checks,
                text=f"{value} (custom)",
                variable=variable,
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 12), pady=2)
            self.variables[value] = variable
        self.custom_var.set("")

    def values(self) -> tuple[str, ...]:
        if self.allow_all and self.all_var.get():
            return ()
        return tuple(value for value, variable in self.variables.items() if variable.get())


class TransformStepDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, step: TransformStep | None = None) -> None:
        super().__init__(parent)
        self.title("Transform Step")
        size_and_center(self, 520, 300)
        self.transient(parent)
        self.grab_set()
        self.result: TransformStep | None = None
        self.kind_var = tk.StringVar(
            value=TRANSFORM_LABELS[step.kind] if step else TRANSFORM_LABELS["trim"]
        )
        self.value_var = tk.StringVar(value=step.value if step else "")
        self.start_var = tk.StringVar(
            value="" if step is None or step.start is None else str(step.start)
        )
        self.end_var = tk.StringVar(value="" if step is None or step.end is None else str(step.end))
        self.sample_var = tk.StringVar(value="Example123")
        self.output_var = tk.StringVar()

        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Transform").grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(
            form,
            textvariable=self.kind_var,
            values=list(TRANSFORM_VALUES),
            state="readonly",
        )
        combo.grid(row=0, column=1, sticky="ew", padx=8)
        combo.bind("<<ComboboxSelected>>", self._refresh_fields)
        self.value_label = ttk.Label(form, text="Value")
        self.value_entry = ttk.Entry(form, textvariable=self.value_var)
        self.start_label = ttk.Label(form, text="Start position")
        self.start_entry = ttk.Entry(form, textvariable=self.start_var)
        self.end_label = ttk.Label(form, text="End position")
        self.end_entry = ttk.Entry(form, textvariable=self.end_var)
        ttk.Label(form, text="Sample input").grid(row=4, column=0, sticky="w", pady=(14, 4))
        sample = ttk.Entry(form, textvariable=self.sample_var)
        sample.grid(row=4, column=1, sticky="ew", padx=8, pady=(14, 4))
        ttk.Label(form, text="Sample output").grid(row=5, column=0, sticky="w")
        ttk.Label(form, textvariable=self.output_var).grid(row=5, column=1, sticky="w", padx=8)
        for variable in (
            self.kind_var,
            self.value_var,
            self.start_var,
            self.end_var,
            self.sample_var,
        ):
            variable.trace_add("write", lambda *_: self._update_sample())
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Apply", command=self._apply).pack(side="right", padx=(0, 8))
        self._refresh_fields()

    def _refresh_fields(self, _: object | None = None) -> None:
        for widget in (
            self.value_label,
            self.value_entry,
            self.start_label,
            self.start_entry,
            self.end_label,
            self.end_entry,
        ):
            widget.grid_remove()
        kind = TRANSFORM_VALUES[self.kind_var.get()]
        if kind == "substring":
            self.start_label.grid(row=1, column=0, sticky="w", pady=6)
            self.start_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
            self.end_label.grid(row=2, column=0, sticky="w", pady=6)
            self.end_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        elif kind not in {"trim", "strip_leading_zeros"}:
            self.value_label.grid(row=1, column=0, sticky="w", pady=6)
            self.value_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        self._update_sample()

    def _step(self) -> TransformStep:
        kind = TRANSFORM_VALUES[self.kind_var.get()]
        start = int(self.start_var.get()) if self.start_var.get().strip() else None
        end = int(self.end_var.get()) if self.end_var.get().strip() else None
        return TransformStep(kind, self.value_var.get(), start, end)

    def _update_sample(self) -> None:
        try:
            self.output_var.set(self._step().apply(self.sample_var.get()))
        except (ValueError, KeyError):
            self.output_var.set("Invalid transform settings")

    def _apply(self) -> None:
        try:
            step = self._step()
            step.validate()
        except ValueError as error:
            messagebox.showerror("Transform Step", str(error), parent=self)
            return
        self.result = step
        self.destroy()


class RuleDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        discovered_account_types: tuple[str, ...],
        discovered_domains: tuple[str, ...],
        rule: MatchingRule | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Matching Rule")
        size_and_center(self, 820, 700)
        self.transient(parent)
        self.grab_set()
        self.result: MatchingRule | None = None
        self.transforms = list(rule.transforms if rule else ())
        self.name_var = tk.StringVar(value=rule.name if rule else "")
        self.enabled_var = tk.BooleanVar(value=True if rule is None else rule.enabled)
        self.target_var = tk.StringVar(
            value=TARGET_LABELS[rule.target_field if rule else "LoginBarcode"]
        )
        self.sample_var = tk.StringVar(value="001234")
        self.sample_output_var = tk.StringVar()

        body = ScrollableFrame(self, padding=14)
        body.pack(fill="both", expand=True)
        form = body.content
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Rule name").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Checkbutton(form, text="Enabled", variable=self.enabled_var).grid(
            row=1, column=1, sticky="w", pady=6
        )
        ttk.Label(form, text="Odin source").grid(row=2, column=0, sticky="w")
        ttk.Combobox(form, values=("ID Number",), state="readonly").grid(
            row=2, column=1, sticky="ew", padx=8
        )
        source = form.grid_slaves(row=2, column=1)[0]
        source.set("ID Number")
        ttk.Label(form, text="Lunchtab target").grid(row=3, column=0, sticky="w", pady=6)
        target = ttk.Combobox(
            form,
            textvariable=self.target_var,
            values=list(TARGET_VALUES),
            state="readonly",
        )
        target.grid(row=3, column=1, sticky="ew", padx=8, pady=6)
        target.bind("<<ComboboxSelected>>", self._target_changed)

        selected_types = rule.account_types if rule else ()
        self.account_choices = ChoiceChecklist(
            form,
            "Applicable Odin account types",
            discovered_account_types,
            selected_types,
            allow_all=True,
            all_selected=not selected_types,
        )
        self.account_choices.grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
        selected_domains = rule.allowed_email_domains if rule else ()
        self.domain_choices = ChoiceChecklist(
            form,
            "Allowed email domains",
            discovered_domains,
            selected_domains,
            allow_all=True,
            all_selected=not selected_domains,
            input_hint="Add one domain at a time without @ (example: school.org).",
            tooltip=(
                "Enter only the domain, without @. Add multiple domains individually. "
                "Matching is exact and case-insensitive, so school.org does not include "
                "sub.school.org."
            ),
            normalize=lambda value: value.strip().casefold(),
            validate=valid_email_domain,
            invalid_message="Enter a valid domain without @, for example school.org.",
        )
        self.domain_choices.grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)

        transforms = ttk.LabelFrame(form, text="Ordered transform pipeline", padding=8)
        transforms.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=8)
        transforms.columnconfigure(0, weight=1)
        transform_table = ttk.Frame(transforms)
        transform_table.grid(row=0, column=0, sticky="nsew")
        self.transform_tree = ttk.Treeview(
            transform_table, columns=("step",), show="headings", height=6
        )
        self.transform_tree.heading("step", text="Transform step")
        self.transform_tree.column("step", width=600)
        add_tree_scrollbars(transform_table, self.transform_tree)
        controls = ttk.Frame(transforms)
        controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        responsive_button_grid(
            controls,
            [
                ("Add step", self._add_transform),
                ("Edit step", self._edit_transform),
                ("Remove step", self._remove_transform),
                ("Move up", lambda: self._move_transform(-1)),
                ("Move down", lambda: self._move_transform(1)),
            ],
        )
        sample = ttk.LabelFrame(form, text="Live transform preview", padding=8)
        sample.grid(row=7, column=0, columnspan=2, sticky="ew", pady=8)
        sample.columnconfigure(1, weight=1)
        ttk.Label(sample, text="Sample Odin ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(sample, textvariable=self.sample_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(sample, text="Result").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Label(sample, textvariable=self.sample_output_var).grid(
            row=1, column=1, sticky="w", padx=8, pady=6
        )
        self.sample_var.trace_add("write", lambda *_: self._update_sample())

        actions = ttk.Frame(self, padding=14)
        actions.pack(fill="x")
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Save rule", command=self._save).pack(side="right", padx=(0, 8))
        self._refresh_transforms()
        self._target_changed()

    def _target_changed(self, _: object | None = None) -> None:
        if TARGET_VALUES[self.target_var.get()] == "EmailUsername":
            self.domain_choices.grid()
        else:
            self.domain_choices.grid_remove()

    def _refresh_transforms(self) -> None:
        self.transform_tree.delete(*self.transform_tree.get_children())
        for index, step in enumerate(self.transforms):
            self.transform_tree.insert("", "end", iid=str(index), values=(transform_label(step),))
        self._update_sample()

    def _selected_transform(self) -> int | None:
        selected = self.transform_tree.selection()
        return int(selected[0]) if selected else None

    def _open_transform(self, step: TransformStep | None = None) -> TransformStep | None:
        dialog = TransformStepDialog(self, step)
        self.wait_window(dialog)
        return dialog.result

    def _add_transform(self) -> None:
        step = self._open_transform()
        if step:
            self.transforms.append(step)
            self._refresh_transforms()

    def _edit_transform(self) -> None:
        index = self._selected_transform()
        if index is None:
            return
        step = self._open_transform(self.transforms[index])
        if step:
            self.transforms[index] = step
            self._refresh_transforms()

    def _remove_transform(self) -> None:
        index = self._selected_transform()
        if index is not None:
            self.transforms.pop(index)
            self._refresh_transforms()

    def _move_transform(self, offset: int) -> None:
        index = self._selected_transform()
        if index is None or not 0 <= index + offset < len(self.transforms):
            return
        self.transforms[index], self.transforms[index + offset] = (
            self.transforms[index + offset],
            self.transforms[index],
        )
        self._refresh_transforms()
        self.transform_tree.selection_set(str(index + offset))

    def _update_sample(self) -> None:
        value = self.sample_var.get()
        try:
            for step in self.transforms:
                value = step.apply(value)
            self.sample_output_var.set(value)
        except ValueError:
            self.sample_output_var.set("Invalid transform settings")

    def _save(self) -> None:
        target = TARGET_VALUES[self.target_var.get()]
        domains = self.domain_choices.values() if target == "EmailUsername" else ()
        try:
            rule = MatchingRule(
                name=self.name_var.get().strip(),
                target_field=target,
                account_types=self.account_choices.values(),
                transforms=tuple(self.transforms),
                enabled=self.enabled_var.get(),
                allowed_email_domains=domains,
            )
            rule.validate()
        except ValueError as error:
            messagebox.showerror("Matching Rule", str(error), parent=self)
            return
        self.result = rule
        self.destroy()


class CrosswalkDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        account_types: tuple[str, ...],
        domains: tuple[str, ...],
    ) -> None:
        super().__init__(parent)
        self.title("Crosswalk Mapping")
        size_and_center(self, 620, 500)
        self.transient(parent)
        self.grab_set()
        self.result: CrosswalkEntry | None = None
        self.account_var = tk.StringVar()
        self.odin_var = tk.StringVar()
        self.target_var = tk.StringVar(value=TARGET_LABELS["LoginBarcode"])
        self.target_value_var = tk.StringVar()
        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Account type").grid(row=0, column=0, sticky="w")
        ttk.Combobox(form, textvariable=self.account_var, values=account_types).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Label(form, text="Odin ID").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.odin_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=6
        )
        ttk.Label(form, text="Lunchtab target").grid(row=2, column=0, sticky="w")
        target = ttk.Combobox(
            form,
            textvariable=self.target_var,
            values=list(TARGET_VALUES),
            state="readonly",
        )
        target.grid(row=2, column=1, sticky="ew", padx=8)
        target.bind("<<ComboboxSelected>>", self._target_changed)
        ttk.Label(form, text="Target value").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.target_value_var).grid(
            row=3, column=1, sticky="ew", padx=8, pady=6
        )
        self.domains = ChoiceChecklist(
            form,
            "Allowed email domains",
            domains,
            (),
            allow_all=True,
            all_selected=True,
            input_hint="Add one domain at a time without @ (example: school.org).",
            tooltip=(
                "Enter only the domain, without @. Add multiple domains individually. "
                "Matching is exact and case-insensitive, so school.org does not include "
                "sub.school.org."
            ),
            normalize=lambda value: value.strip().casefold(),
            validate=valid_email_domain,
            invalid_message="Enter a valid domain without @, for example school.org.",
        )
        self.domains.grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
        actions = ttk.Frame(self, padding=14)
        actions.pack(fill="x")
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Add mapping", command=self._save).pack(side="right", padx=(0, 8))
        self._target_changed()

    def _target_changed(self, _: object | None = None) -> None:
        if TARGET_VALUES[self.target_var.get()] == "EmailUsername":
            self.domains.grid()
        else:
            self.domains.grid_remove()

    def _save(self) -> None:
        target = TARGET_VALUES[self.target_var.get()]
        try:
            entry = CrosswalkEntry(
                self.account_var.get().strip(),
                self.odin_var.get().strip(),
                target,
                self.target_value_var.get().strip(),
                self.domains.values() if target == "EmailUsername" else (),
            )
            entry.validate()
        except ValueError as error:
            messagebox.showerror("Crosswalk Mapping", str(error), parent=self)
            return
        self.result = entry
        self.destroy()


class PreviewWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, preview: ProfilePreview) -> None:
        super().__init__(parent)
        self.title("Profile Dry-Run Preview")
        size_and_center(self, 900, 680)
        body = ScrollableFrame(self, padding=14)
        body.pack(fill="both", expand=True)
        content = body.content
        ttk.Label(
            content,
            text=f"Profile: {preview.profile_name}",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        summary = ttk.LabelFrame(content, text="Summary", padding=10)
        summary.pack(fill="x", pady=10)
        values = (
            ("Matched", preview.matched),
            ("Crosswalk", preview.crosswalk_matches),
            ("Identifier rules", preview.rule_matches),
            ("Name fallback", preview.name_matches),
            ("Conflicts", preview.conflicts),
            ("Unmatched", preview.unmatched),
            ("Manual review", preview.manual_review),
            ("Changed from Legacy", preview.changed_from_legacy),
        )
        for index, (label, value) in enumerate(values):
            ttk.Label(summary, text=f"{label}: {value}").grid(
                row=index // 2, column=index % 2, sticky="w", padx=8, pady=3
            )
        rules = ttk.LabelFrame(content, text="Matches by rule", padding=8)
        rules.pack(fill="x", pady=8)
        rule_table = ttk.Frame(rules)
        rule_table.pack(fill="both", expand=True)
        tree = ttk.Treeview(rule_table, columns=("rule", "count"), show="headings", height=6)
        tree.heading("rule", text="Rule")
        tree.heading("count", text="Matches")
        for name, count in preview.matches_by_rule.items():
            tree.insert("", "end", values=(name, count))
        add_tree_scrollbars(rule_table, tree)
        samples = ttk.LabelFrame(content, text="Representative transformations", padding=8)
        samples.pack(fill="both", expand=True, pady=8)
        text = tk.Text(samples, height=12, wrap="word")
        text.insert("1.0", "\n".join(preview.samples) if preview.samples else "None")
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        actions = ttk.Frame(self, padding=14)
        actions.pack(fill="x")
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right")


class ProfileEditor(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        profile: MatchingProfile,
        account_types: tuple[str, ...],
        domains: tuple[str, ...],
        source_paths: tuple[Path, Path] | None,
    ) -> None:
        super().__init__(parent)
        self.title("Matching Profile Editor")
        size_and_center(self, 1000, 720)
        self.transient(parent)
        self.grab_set()
        self.original = profile
        self.account_types = account_types
        self.domains = domains
        self.source_paths = source_paths
        self.rules = list(profile.rules)
        self.crosswalk = list(profile.crosswalk)
        self.saved_profile: MatchingProfile | None = None
        self.preview_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.preview_busy = False
        self.name_var = tk.StringVar(value=profile.name)
        self.description_var = tk.StringVar(value=profile.description)
        self.preview_status_var = tk.StringVar()

        body = ScrollableFrame(self, padding=14)
        body.pack(fill="both", expand=True)
        details = ttk.LabelFrame(body.content, text="Venue profile", padding=10)
        details.pack(fill="x")
        details.columnconfigure(1, weight=1)
        ttk.Label(details, text="Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(details, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(details, text="Description").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(details, textvariable=self.description_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=6
        )
        self.fallback_choices = ChoiceChecklist(
            details,
            "Unique-name fallback account types",
            account_types,
            profile.name_fallback_account_types,
            allow_all=True,
            all_selected=profile.name_fallback_all,
        )
        self.fallback_choices.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)

        notebook = ttk.Notebook(body.content)
        notebook.pack(fill="both", expand=True, pady=12)
        rules_tab = ttk.Frame(notebook, padding=8)
        crosswalk_tab = ttk.Frame(notebook, padding=8)
        notebook.add(rules_tab, text="Ordered matching rules")
        notebook.add(crosswalk_tab, text="Persistent crosswalk")
        rules_tab.rowconfigure(0, weight=1)
        rules_tab.columnconfigure(0, weight=1)
        rule_table = ttk.Frame(rules_tab)
        rule_table.grid(row=0, column=0, sticky="nsew")
        self.rules_tree = ttk.Treeview(
            rule_table,
            columns=("name", "enabled", "target", "scope", "domains", "transforms"),
            show="headings",
            height=12,
        )
        for column, title, width in (
            ("name", "Rule", 150),
            ("enabled", "Enabled", 70),
            ("target", "Target", 120),
            ("scope", "Account types", 180),
            ("domains", "Email domains", 180),
            ("transforms", "Transform pipeline", 360),
        ):
            self.rules_tree.heading(column, text=title)
            self.rules_tree.column(column, width=width)
        add_tree_scrollbars(rule_table, self.rules_tree)
        rule_actions = ttk.Frame(rules_tab)
        rule_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        responsive_button_grid(
            rule_actions,
            [
                ("Add rule", self._add_rule),
                ("Edit", self._edit_rule),
                ("Remove", self._remove_rule),
                ("Move up", lambda: self._move_rule(-1)),
                ("Move down", lambda: self._move_rule(1)),
            ],
        )

        crosswalk_tab.rowconfigure(0, weight=1)
        crosswalk_tab.columnconfigure(0, weight=1)
        crosswalk_table = ttk.Frame(crosswalk_tab)
        crosswalk_table.grid(row=0, column=0, sticky="nsew")
        self.crosswalk_tree = ttk.Treeview(
            crosswalk_table,
            columns=("account", "odin", "field", "target", "domains"),
            show="headings",
            height=12,
        )
        for column, title, width in (
            ("account", "Account type", 180),
            ("odin", "Odin ID", 150),
            ("field", "Target", 130),
            ("target", "Target value", 220),
            ("domains", "Email domains", 180),
        ):
            self.crosswalk_tree.heading(column, text=title)
            self.crosswalk_tree.column(column, width=width)
        add_tree_scrollbars(crosswalk_table, self.crosswalk_tree)
        crosswalk_actions = ttk.Frame(crosswalk_tab)
        crosswalk_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        responsive_button_grid(
            crosswalk_actions,
            [
                ("Add mapping", self._add_crosswalk),
                ("Remove", self._remove_crosswalk),
                ("Import CSV", self._import_crosswalk),
                ("Export CSV", self._export_crosswalk),
            ],
        )
        actions = ttk.Frame(self, padding=14)
        actions.pack(fill="x")
        self.preview_button = ttk.Button(
            actions,
            text="Dry-run preview",
            command=self._preview,
        )
        self.preview_button.pack(side="left")
        self.preview_progress = ttk.Progressbar(
            actions,
            mode="indeterminate",
            length=150,
        )
        self.preview_progress.pack(side="left", padx=(10, 0))
        ttk.Label(actions, textvariable=self.preview_status_var).pack(
            side="left",
            padx=(8, 0),
        )
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="Save profile", command=self._save).pack(side="right", padx=(0, 8))
        self._refresh()

    def _profile(self) -> MatchingProfile:
        fallback = self.fallback_choices.values()
        return MatchingProfile(
            profile_id=self.original.profile_id,
            name=self.name_var.get().strip(),
            description=self.description_var.get().strip(),
            rules=tuple(self.rules),
            crosswalk=tuple(self.crosswalk),
            name_fallback_account_types=fallback,
            name_fallback_all=self.fallback_choices.all_var.get(),
        )

    def _refresh(self) -> None:
        self.rules_tree.delete(*self.rules_tree.get_children())
        for index, rule in enumerate(self.rules):
            self.rules_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    rule.name,
                    "Yes" if rule.enabled else "No",
                    TARGET_LABELS[rule.target_field],
                    ", ".join(rule.account_types) or "All",
                    ", ".join(rule.allowed_email_domains) or "Any",
                    " → ".join(transform_label(step) for step in rule.transforms) or "Exact",
                ),
            )
        self.crosswalk_tree.delete(*self.crosswalk_tree.get_children())
        for index, entry in enumerate(self.crosswalk):
            self.crosswalk_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    entry.account_type,
                    entry.odin_id,
                    TARGET_LABELS[entry.target_field],
                    entry.target_value,
                    ", ".join(entry.allowed_email_domains) or "Any",
                ),
            )

    def _selected_rule(self) -> int | None:
        selected = self.rules_tree.selection()
        return int(selected[0]) if selected else None

    def _open_rule(self, rule: MatchingRule | None = None) -> MatchingRule | None:
        dialog = RuleDialog(self, self.account_types, self.domains, rule)
        self.wait_window(dialog)
        return dialog.result

    def _add_rule(self) -> None:
        rule = self._open_rule()
        if rule:
            self.rules.append(rule)
            self._refresh()

    def _edit_rule(self) -> None:
        index = self._selected_rule()
        if index is None:
            return
        rule = self._open_rule(self.rules[index])
        if rule:
            self.rules[index] = rule
            self._refresh()

    def _remove_rule(self) -> None:
        index = self._selected_rule()
        if index is not None:
            self.rules.pop(index)
            self._refresh()

    def _move_rule(self, offset: int) -> None:
        index = self._selected_rule()
        if index is None or not 0 <= index + offset < len(self.rules):
            return
        self.rules[index], self.rules[index + offset] = (
            self.rules[index + offset],
            self.rules[index],
        )
        self._refresh()
        self.rules_tree.selection_set(str(index + offset))

    def _add_crosswalk(self) -> None:
        dialog = CrosswalkDialog(self, self.account_types, self.domains)
        self.wait_window(dialog)
        if dialog.result:
            self.crosswalk.append(dialog.result)
            self._refresh()

    def _remove_crosswalk(self) -> None:
        selected = self.crosswalk_tree.selection()
        if selected:
            self.crosswalk.pop(int(selected[0]))
            self._refresh()

    def _import_crosswalk(self) -> None:
        selected = filedialog.askopenfilename(parent=self, filetypes=[("CSV files", "*.csv")])
        if selected:
            try:
                self.crosswalk = list(import_crosswalk(Path(selected)))
                self._refresh()
            except ValueError as error:
                messagebox.showerror("Matching Profile", str(error), parent=self)

    def _export_crosswalk(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if selected and messagebox.askyesno(
            "Export Crosswalk",
            "Crosswalk exports contain account identifiers. Save only in an approved "
            "secure location?",
            parent=self,
        ):
            export_crosswalk(
                replace(self._profile(), crosswalk=tuple(self.crosswalk)),
                Path(selected),
            )

    def _preview(self) -> None:
        if self.preview_busy:
            return
        if not self.source_paths:
            messagebox.showinfo(
                "Dry-Run Preview",
                "Select and validate source files on the main screen first.",
                parent=self,
            )
            return
        try:
            profile = self._profile()
            profile.validate()
        except ValueError as error:
            messagebox.showerror("Dry-Run Preview", str(error), parent=self)
            return
        self._set_preview_busy(True)

        def work() -> None:
            try:
                preview = preview_profile(*self.source_paths, profile)  # type: ignore[misc]
                self.preview_events.put(("success", preview))
            except Exception as error:
                self.preview_events.put(("error", error))

        threading.Thread(target=work, daemon=True).start()
        self.after(75, self._poll_preview)

    def _set_preview_busy(self, busy: bool) -> None:
        self.preview_busy = busy
        self.preview_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.preview_status_var.set("Running dry-run preview…")
            self.preview_progress.start(10)
        else:
            self.preview_status_var.set("")
            self.preview_progress.stop()

    def _poll_preview(self) -> None:
        try:
            status, payload = self.preview_events.get_nowait()
        except queue.Empty:
            if self.preview_busy and self.winfo_exists():
                self.after(75, self._poll_preview)
            return

        self._set_preview_busy(False)
        if status == "success":
            PreviewWindow(self, payload)  # type: ignore[arg-type]
        else:
            messagebox.showerror("Dry-Run Preview", str(payload), parent=self)

    def _save(self) -> None:
        try:
            profile = self._profile()
            profile.validate()
            save_profile(profile)
        except ValueError as error:
            messagebox.showerror("Matching Profile", str(error), parent=self)
            return
        self.saved_profile = profile
        self.destroy()


class ProfileManager(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        account_types: tuple[str, ...] = (),
        domains: tuple[str, ...] = (),
        source_paths: tuple[Path, Path] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Manage Matching Profiles")
        size_and_center(self, 760, 520)
        self.transient(parent)
        self.grab_set()
        self.account_types = account_types
        self.domains = domains
        self.source_paths = source_paths
        self.profiles = list_profiles()
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        table = ttk.Frame(body)
        table.grid(row=0, column=0, sticky="nsew")
        self.tree = ttk.Treeview(
            table,
            columns=("name", "rules", "crosswalk", "readonly"),
            show="headings",
        )
        for column, title, width in (
            ("name", "Profile", 280),
            ("rules", "Rules", 80),
            ("crosswalk", "Crosswalk", 100),
            ("readonly", "Protected", 90),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)
        add_tree_scrollbars(table, self.tree)
        controls = ttk.Frame(body)
        controls.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        responsive_button_grid(
            controls,
            [
                ("New from Legacy", self._new),
                ("Edit", self._edit),
                ("Duplicate", self._duplicate),
                ("Import", self._import),
                ("Export", self._export),
                ("Delete", self._delete),
            ],
        )
        actions = ttk.Frame(self, padding=14)
        actions.pack(fill="x")
        ttk.Button(actions, text="Close", command=self.destroy).pack(side="right")
        self._refresh()

    def _refresh(self) -> None:
        self.profiles = list_profiles()
        self.tree.delete(*self.tree.get_children())
        for index, profile in enumerate(self.profiles):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    profile.name,
                    len(profile.rules),
                    len(profile.crosswalk),
                    "Yes" if profile.read_only else "No",
                ),
            )

    def _selected(self) -> MatchingProfile | None:
        selected = self.tree.selection()
        return self.profiles[int(selected[0])] if selected else None

    def _open_editor(self, profile: MatchingProfile) -> None:
        editor = ProfileEditor(
            self,
            profile,
            self.account_types,
            self.domains,
            self.source_paths,
        )
        self.wait_window(editor)
        self._refresh()

    def _new(self) -> None:
        name = simpledialog.askstring("New Profile", "Profile name:", parent=self)
        if name:
            self._open_editor(duplicate_profile(self.profiles[0], name))

    def _edit(self) -> None:
        profile = self._selected()
        if not profile:
            return
        if profile.read_only:
            messagebox.showinfo(
                "Matching Profiles",
                "Legacy Default is protected. Duplicate it to customize.",
                parent=self,
            )
            return
        self._open_editor(profile)

    def _duplicate(self) -> None:
        profile = self._selected()
        if not profile:
            return
        name = simpledialog.askstring(
            "Duplicate Profile",
            "New profile name:",
            initialvalue=f"{profile.name} Copy",
            parent=self,
        )
        if name:
            self._open_editor(duplicate_profile(profile, name))

    def _import(self) -> None:
        selected = filedialog.askopenfilename(parent=self, filetypes=[("JSON profiles", "*.json")])
        if selected:
            try:
                save_profile(import_profile(Path(selected)))
                self._refresh()
            except ValueError as error:
                messagebox.showerror("Matching Profiles", str(error), parent=self)

    def _export(self) -> None:
        profile = self._selected()
        if not profile:
            return
        selected = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            filetypes=[("JSON profiles", "*.json")],
        )
        if selected and messagebox.askyesno(
            "Export Profile",
            "Profiles may contain account identifiers. Save only in an approved secure location?",
            parent=self,
        ):
            export_profile(profile, Path(selected))

    def _delete(self) -> None:
        profile = self._selected()
        if profile:
            try:
                delete_profile(profile)
                self._refresh()
            except ValueError as error:
                messagebox.showerror("Matching Profiles", str(error), parent=self)
