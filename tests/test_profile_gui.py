from __future__ import annotations

import tkinter as tk
import time
from pathlib import Path
from tkinter import ttk

from odin_lunchtab.managed import ProfilePreview
from odin_lunchtab.gui import BalanceTransferApp
from odin_lunchtab.profile_gui import (
    ChoiceChecklist,
    PreviewWindow,
    ProfileEditor,
    ProfileManager,
    RuleDialog,
)
from odin_lunchtab.profiles import (
    LEGACY_DEFAULT_PROFILE,
    MatchingRule,
    duplicate_profile,
    valid_email_domain,
)
from odin_lunchtab.ui_helpers import size_and_center


def test_choice_checklist_preserves_discovered_and_custom_values() -> None:
    root = tk.Tk()
    root.withdraw()
    widget = ChoiceChecklist(
        root,
        "Types",
        ("Student", "Staff"),
        ("Staff", "Guest"),
        allow_all=True,
    )

    assert widget.values() == ("Staff", "Guest")
    assert "Guest" in widget.variables
    root.destroy()


def test_adding_custom_value_switches_off_all_values() -> None:
    root = tk.Tk()
    root.withdraw()
    widget = ChoiceChecklist(
        root,
        "Types",
        ("Student", "Staff"),
        (),
        allow_all=True,
        all_selected=True,
    )

    widget.custom_var.set("Guest")
    widget._add_custom()

    assert not widget.all_var.get()
    assert widget.values() == ("Guest",)
    root.destroy()


def test_adding_existing_value_switches_off_all_values_and_selects_it() -> None:
    root = tk.Tk()
    root.withdraw()
    widget = ChoiceChecklist(
        root,
        "Types",
        ("Student", "Staff"),
        (),
        allow_all=True,
        all_selected=True,
    )

    widget.custom_var.set("Staff")
    widget._add_custom()

    assert not widget.all_var.get()
    assert widget.values() == ("Staff",)
    root.destroy()


def test_domain_input_explains_format_normalizes_and_rejects_at_sign() -> None:
    root = tk.Tk()
    root.withdraw()
    widget = ChoiceChecklist(
        root,
        "Allowed email domains",
        (),
        (),
        allow_all=True,
        all_selected=True,
        input_hint="Add one domain at a time without @ (example: school.org).",
        tooltip="Enter only the domain, without @. Add multiple domains individually.",
        normalize=lambda value: value.strip().casefold(),
        validate=valid_email_domain,
        invalid_message="Enter a valid domain without @, for example school.org.",
    )

    widget.custom_var.set("@school.org")
    widget._add_custom()
    assert widget.all_var.get()
    assert "without @" in widget.error_var.get()

    widget.custom_var.set(" School.ORG ")
    widget._add_custom()
    assert not widget.all_var.get()
    assert widget.values() == ("school.org",)
    assert "one domain at a time" in widget.hint_var.get()
    assert widget.error_var.get() == ""
    root.destroy()


def test_rule_dialog_toggles_email_domain_controls() -> None:
    root = tk.Tk()
    root.withdraw()
    dialog = RuleDialog(
        root,
        ("Staff",),
        ("school.org",),
        MatchingRule("Email", target_field="EmailUsername"),
    )
    root.update_idletasks()
    assert dialog.domain_choices.winfo_ismapped()

    dialog.target_var.set("Login barcode")
    dialog._target_changed()
    root.update_idletasks()
    assert not dialog.domain_choices.winfo_ismapped()
    dialog.destroy()
    root.destroy()


def test_profile_editor_shows_spinner_while_dry_run_is_processing(monkeypatch) -> None:
    root = tk.Tk()
    root.withdraw()
    preview = ProfilePreview("Spinner", 1, 0, 1, 0, 0, 0, 0, 1, {}, ("sample",))

    def delayed_preview(*_args):
        time.sleep(0.1)
        return preview

    opened: list[ProfilePreview] = []
    monkeypatch.setattr("odin_lunchtab.profile_gui.preview_profile", delayed_preview)
    monkeypatch.setattr(
        "odin_lunchtab.profile_gui.PreviewWindow",
        lambda _parent, result: opened.append(result),
    )
    editor = ProfileEditor(
        root,
        duplicate_profile(LEGACY_DEFAULT_PROFILE, "Spinner"),
        ("Staff",),
        ("school.org",),
        (Path("odin.xlsx"), Path("lunchtab.csv")),
    )

    editor._preview()
    assert editor.preview_busy
    assert editor.preview_button.instate(("disabled",))
    assert editor.preview_status_var.get() == "Running dry-run preview…"

    deadline = time.monotonic() + 2
    while editor.preview_busy and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)

    assert not editor.preview_busy
    assert editor.preview_button.instate(("!disabled",))
    assert editor.preview_status_var.get() == ""
    assert opened == [preview]
    editor.destroy()
    root.destroy()


def test_responsive_windows_keep_primary_actions_mapped() -> None:
    root = tk.Tk()
    root.withdraw()
    root.winfo_screenwidth = lambda: 1366  # type: ignore[method-assign]
    root.winfo_screenheight = lambda: 768  # type: ignore[method-assign]
    assert size_and_center(root, 1000, 720) == (1000, 652)

    main = tk.Toplevel(root)
    app = BalanceTransferApp(main)
    manager = ProfileManager(root)
    editor = ProfileEditor(
        root,
        duplicate_profile(LEGACY_DEFAULT_PROFILE, "Sizing"),
        ("Staff",),
        ("school.org",),
        None,
    )
    preview = PreviewWindow(
        root,
        ProfilePreview("Sizing", 1, 0, 1, 0, 0, 0, 0, 1, {}, ("sample",)),
    )
    root.update_idletasks()
    assert app.validate_button.winfo_ismapped()
    assert app.process_button.winfo_ismapped()
    assert any(
        child.cget("text") == "Close" for child in manager.winfo_children()[-1].winfo_children()
    )
    assert any(
        isinstance(child, ttk.Button) and child.cget("text") == "Save profile"
        for child in editor.winfo_children()[-1].winfo_children()
    )
    assert any(
        child.cget("text") == "Close" for child in preview.winfo_children()[-1].winfo_children()
    )
    preview.destroy()
    editor.destroy()
    manager.destroy()
    main.destroy()
    root.destroy()
