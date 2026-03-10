"""XP-like visual theme and shared UI text."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PREVIEW_LENGTH = 600
FILE_READ_TIMEOUT = 180
DESC_WRAP_LENGTH = 1000

XP_BG = "#ECE9D8"
XP_PANEL = "#D4D0C8"
XP_WHITE = "#FFFFFF"
XP_TEXT = "#000000"
XP_STATUS_BG = "#F1EFE2"

TOOL_DESCRIPTION = (
    "Analyze PDF files in a folder and manage filename updates safely. "
    "External API integration is optional."
)
FOOTER_TEXT = "Rule-based rename | MCP: context7 | Rollback with before/after names"


def apply_xp_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    theme_names = set(style.theme_names())
    if "xpnative" in theme_names:
        style.theme_use("xpnative")
    elif "winnative" in theme_names:
        style.theme_use("winnative")
    elif "classic" in theme_names:
        style.theme_use("classic")
    else:
        style.theme_use("clam")

    root.option_add("*Font", "Tahoma 9")

    style.configure(
        ".",
        background=XP_BG,
        foreground=XP_TEXT,
        fieldbackground=XP_WHITE,
        font=("Tahoma", 9),
    )
    style.configure("TFrame", background=XP_BG)
    style.configure("TLabel", background=XP_BG, foreground=XP_TEXT)
    style.configure("TLabelframe", background=XP_BG, foreground=XP_TEXT, borderwidth=1, relief="groove")
    style.configure("TLabelframe.Label", background=XP_BG, foreground=XP_TEXT, font=("Tahoma", 9, "bold"))
    style.configure(
        "TEntry",
        fieldbackground=XP_WHITE,
        foreground=XP_TEXT,
        insertcolor=XP_TEXT,
        borderwidth=1,
        relief="sunken",
        padding=3,
    )
    style.configure(
        "TButton",
        background=XP_PANEL,
        foreground=XP_TEXT,
        borderwidth=1,
        relief="raised",
        padding=(8, 3),
    )
    style.map(
        "TButton",
        background=[("active", "#E6E2D3"), ("pressed", "#C8C4B8")],
        relief=[("pressed", "sunken")],
        foreground=[("disabled", "#777777")],
    )
    style.configure("TCheckbutton", background=XP_BG, foreground=XP_TEXT)

