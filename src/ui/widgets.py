"""Reusable UI widgets/dialogs for the desktop app."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk

from src.ui.styles import XP_BG, XP_TEXT, XP_WHITE


def ask_new_filename(parent: tk.Tk, current_name: str) -> str | None:
    result: list[str | None] = [None]

    top = tk.Toplevel(parent)
    top.title("Rename File")
    top.transient(parent)
    top.grab_set()
    top.configure(bg=XP_BG)
    ttk.Label(top, text="New filename").pack(anchor=tk.W, padx=10, pady=(10, 0))
    entry = ttk.Entry(top, width=56)
    entry.pack(fill=tk.X, padx=10, pady=6)
    entry.insert(0, current_name)
    entry.select_range(0, tk.END)
    entry.focus_set()

    def on_ok():
        result[0] = entry.get().strip()
        top.destroy()

    def on_cancel():
        top.destroy()

    bar = ttk.Frame(top)
    bar.pack(pady=(0, 10))
    ttk.Button(bar, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
    ttk.Button(bar, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=4)
    top.bind("<Return>", lambda _: on_ok())
    top.bind("<Escape>", lambda _: on_cancel())
    top.wait_window()
    return result[0]


def parse_rules_text(text: str) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "," not in line:
            continue
        key, _, prefix = line.partition(",")
        key = key.strip()
        prefix = prefix.strip()
        if key:
            rules.append((key, prefix or ""))
    return rules


def ask_naming_rules(parent: tk.Tk, initial_rules: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    result: list[tuple[str, str]] | None = None
    initial_text = "\n".join(f"{keyword},{prefix}" for keyword, prefix in initial_rules)

    top = tk.Toplevel(parent)
    top.title("Naming Rules")
    top.transient(parent)
    top.grab_set()
    top.configure(bg=XP_BG)

    ttk.Label(top, text="Format: keyword,prefix (one per line)").pack(anchor=tk.W, padx=10, pady=(10, 0))
    editor = scrolledtext.ScrolledText(
        top,
        width=56,
        height=12,
        font=("Tahoma", 9),
        bg=XP_WHITE,
        fg=XP_TEXT,
        insertbackground=XP_TEXT,
        relief=tk.SUNKEN,
        bd=1,
    )
    editor.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
    editor.insert(tk.END, initial_text)

    def on_ok():
        nonlocal result
        result = parse_rules_text(editor.get("1.0", tk.END))
        if not result:
            result = initial_rules
        top.destroy()

    def on_cancel():
        top.destroy()

    bar = ttk.Frame(top)
    bar.pack(pady=(0, 10))
    ttk.Button(bar, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
    ttk.Button(bar, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=4)
    top.bind("<Return>", lambda _: on_ok())
    top.bind("<Escape>", lambda _: on_cancel())
    top.wait_window()
    return result


def create_readonly_scrolled_text(
    parent: tk.Misc,
    content: str,
    height: int,
    mousewheel_cb,
) -> scrolledtext.ScrolledText:
    widget = scrolledtext.ScrolledText(
        parent,
        height=height,
        wrap=tk.WORD,
        font=("Tahoma", 9),
        bg=XP_WHITE,
        fg=XP_TEXT,
        insertbackground=XP_TEXT,
        relief=tk.SUNKEN,
        bd=1,
    )
    widget.insert(tk.END, content or "(empty)")
    widget.config(state=tk.DISABLED)
    widget.bind("<MouseWheel>", mousewheel_cb)
    return widget
