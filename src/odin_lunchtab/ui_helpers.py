from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class ToolTip:
    def __init__(self, widget: tk.Misc, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _: tk.Event[tk.Misc]) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._window is not None or not self.widget.winfo_exists():
            return
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(
            f"+{self.widget.winfo_rootx() + 12}+"
            f"{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}"
        )
        ttk.Label(
            window,
            text=self.text,
            padding=8,
            relief="solid",
            borderwidth=1,
            wraplength=360,
            justify="left",
        ).pack()
        self._window = window

    def _hide(self, _: tk.Event[tk.Misc] | None = None) -> None:
        self._cancel()
        if self._window is not None:
            self._window.destroy()
            self._window = None


def size_and_center(
    window: tk.Misc,
    preferred_width: int,
    preferred_height: int,
    *,
    max_width_ratio: float = 0.9,
    max_height_ratio: float = 0.85,
) -> tuple[int, int]:
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = min(preferred_width, int(screen_width * max_width_ratio))
    height = min(preferred_height, int(screen_height * max_height_ratio))
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(min(width, 640), min(height, 480))
    return width, height


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, padding: int = 0) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, padding=padding)
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.content.bind("<Configure>", self._update_scrollregion)
        self.canvas.bind("<Configure>", self._resize_content)

    def _update_scrollregion(self, _: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_content(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)


def add_tree_scrollbars(parent: tk.Misc, tree: ttk.Treeview) -> None:
    vertical = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    parent.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)


def responsive_button_grid(
    parent: tk.Misc,
    buttons: list[tuple[str, Callable[[], None]]],
    *,
    columns: int = 3,
) -> list[ttk.Button]:
    widgets: list[ttk.Button] = []
    for index, (text, command) in enumerate(buttons):
        button = ttk.Button(parent, text=text, command=command)
        button.grid(
            row=index // columns,
            column=index % columns,
            sticky="ew",
            padx=(0 if index % columns == 0 else 6, 0),
            pady=(0 if index < columns else 6, 0),
        )
        widgets.append(button)
    for column in range(columns):
        parent.columnconfigure(column, weight=1)
    return widgets
