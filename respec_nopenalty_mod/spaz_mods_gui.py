#!/usr/bin/env python3
"""
SPAZ Mod Manager — GUI.

A small Tkinter GUI around spaz_mods.py. No third-party dependencies (Tkinter
ships with the Python standard library).

Run it with:

    python3 spaz_mods_gui.py

or double-click it (on Windows) if Python is associated with .py files.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import spaz_mods as sm


class ModManagerApp:
    STATUS_COLORS = {
        "PATCHED": "#1e7d1e",   # green
        "ORIGINAL": "#1f4e79",  # blue
        "MISSING": "#b36b00",   # orange
    }
    DEFAULT_COLOR = "#b00000"   # red (MODIFIED / unknown)

    def __init__(self, root):
        self.root = root
        self.game_dir_var = tk.StringVar(value=os.path.dirname(SCRIPT_DIR))
        self._build()
        self.refresh()

    # -- UI construction ---------------------------------------------------
    def _build(self):
        self.root.title("SPAZ Mod Manager")
        self.root.geometry("760x560")

        # Top: game directory.
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Game folder:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.game_dir_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left", padx=2)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=2)

        # Middle: status table.
        table_frame = ttk.Frame(self.root, padding=(8, 0))
        table_frame.pack(fill="both", expand=True)

        cols = ("file", "status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        self.tree.heading("file", text="File")
        self.tree.heading("status", text="Status")
        self.tree.column("file", width=420, anchor="w")
        self.tree.column("status", width=180, anchor="w")
        self.tree.tag_configure("PATCHED", foreground=self.STATUS_COLORS["PATCHED"])
        self.tree.tag_configure("ORIGINAL", foreground=self.STATUS_COLORS["ORIGINAL"])
        self.tree.tag_configure("MISSING", foreground=self.STATUS_COLORS["MISSING"])
        self.tree.tag_configure("MODIFIED", foreground=self.DEFAULT_COLOR)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Bottom: action buttons.
        actions = ttk.Frame(self.root, padding=8)
        actions.pack(fill="x")
        ttk.Button(actions, text="Patch (build)", command=self._patch).pack(side="left", padx=2)
        ttk.Button(actions, text="Apply to game", command=self._apply).pack(side="left", padx=2)
        ttk.Button(actions, text="Revert", command=self._revert).pack(side="left", padx=2)

        # Log area.
        self.log = ScrolledText(self.root, height=10, state="disabled", padx=6, pady=4)
        self.log.pack(fill="both", expand=False, padx=8, pady=(0, 8))

    # -- helpers -----------------------------------------------------------
    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.game_dir_var.get(),
                                    title="Select the game folder")
        if d:
            self.game_dir_var.set(d)
            self.refresh()

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_lines(self, lines):
        for name, msg in lines:
            self._log(f"  {name}: {msg}")

    # -- actions -----------------------------------------------------------
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        game_dir = self.game_dir_var.get()
        for name, status in sm.get_statuses(game_dir):
            tag = status if status in self.STATUS_COLORS else "MODIFIED"
            self.tree.insert("", "end", values=(name, status), tags=(tag,))

    def _patch(self):
        self._log("== Patch (build) ==")
        self._log_lines(sm.run_patch(self.game_dir_var.get()))
        self._log("Done.")
        self.refresh()

    def _apply(self):
        if not messagebox.askyesno(
            "Apply patches",
            "Make sure the game is CLOSED.\n\nApply the patched files to the game?",
        ):
            return
        self._log("== Apply to game ==")
        self._log_lines(sm.run_apply(self.game_dir_var.get()))
        self._log("Done.")
        self.refresh()

    def _revert(self):
        if not messagebox.askyesno(
            "Revert patches",
            "Make sure the game is CLOSED.\n\nRestore the original files?",
        ):
            return
        self._log("== Revert ==")
        self._log_lines(sm.run_revert(self.game_dir_var.get()))
        self._log("Done.")
        self.refresh()


def main():
    root = tk.Tk()
    app = ModManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
