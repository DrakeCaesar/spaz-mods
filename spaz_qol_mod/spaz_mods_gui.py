#!/usr/bin/env python3
"""
SPAZ QoL Mod — GUI (dark mode).

A small Tkinter GUI around spaz_mods.py. No third-party dependencies (Tkinter
ships with the Python standard library).

Run it with:

    python3 spaz_mods_gui.py
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import spaz_mods as sm

MOD_NAME = "SPAZ QoL Mod"
MOD_TAGLINE = "Quality-of-life tweaks for Space Pirates and Zombies."

# Dark palette.
BG = "#1b1b1f"
FG = "#e6e6e6"
PANEL = "#232327"
FIELD = "#2a2a2f"
BUTTON = "#333338"
BUTTON_ACTIVE = "#46464d"
SELECT = "#264f78"
HEADER = "#2d2d33"

STATUS_GREEN = "#6fbf73"
STATUS_BLUE = "#5b9bd5"
STATUS_ORANGE = "#e0a458"
STATUS_RED = "#e05252"


class ModManagerApp:
    STATUS_COLORS = {
        "PATCHED": STATUS_GREEN,
        "ORIGINAL": STATUS_BLUE,
        "MISSING": STATUS_ORANGE,
    }
    DEFAULT_COLOR = STATUS_RED

    def __init__(self, root):
        self.root = root
        self.game_dir_var = tk.StringVar(value=os.path.dirname(SCRIPT_DIR))
        self.desc_var = tk.StringVar()
        self._apply_theme(root)
        self._build()
        self.refresh()

    # -- theme -------------------------------------------------------------
    def _apply_theme(self, root):
        root.configure(bg=BG)
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=FG, fieldbackground=FIELD)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Title.TLabel", background=BG, foreground=FG,
                        font=("Segoe UI", 16, "bold"))
        style.configure("Tagline.TLabel", background=BG, foreground="#9a9aa2",
                        font=("Segoe UI", 9))
        style.configure("Detail.TLabel", background=PANEL, foreground=FG,
                        font=("Segoe UI", 10), padding=10)
        style.configure("TButton", background=BUTTON, foreground=FG,
                        borderwidth=0, focusthickness=0, padding=(12, 5))
        style.map("TButton",
                  background=[("active", BUTTON_ACTIVE), ("pressed", BUTTON_ACTIVE)])
        style.configure("Accent.TButton", background="#1f6feb", foreground="#ffffff",
                        borderwidth=0, focusthickness=0, padding=(12, 5))
        style.map("Accent.TButton", background=[("active", "#3b82f6")])
        style.configure("TEntry", fieldbackground=FIELD, foreground=FG,
                        insertcolor=FG, bordercolor="#3a3a40")
        style.configure("Treeview", background=FIELD, fieldbackground=FIELD,
                        foreground=FG, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=HEADER, foreground=FG,
                        borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("Treeview",
                  background=[("selected", SELECT)],
                  foreground=[("selected", "#ffffff")])

    # -- UI ----------------------------------------------------------------
    def _build(self):
        self.root.title(MOD_NAME)
        self.root.geometry("780x600")

        header = ttk.Frame(self.root, padding=(16, 14, 16, 4))
        header.pack(fill="x")
        ttk.Label(header, text=MOD_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=MOD_TAGLINE, style="Tagline.TLabel").pack(anchor="w")

        # Game folder.
        top = ttk.Frame(self.root, padding=(16, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Game folder:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.game_dir_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left", padx=2)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=2)

        # Status table.
        table_frame = ttk.Frame(self.root, padding=(16, 4))
        table_frame.pack(fill="both", expand=True)

        cols = ("file", "status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=8)
        self.tree.heading("file", text="Mod")
        self.tree.heading("status", text="Status")
        self.tree.column("file", width=430, anchor="w")
        self.tree.column("status", width=180, anchor="w")
        self.tree.tag_configure("PATCHED", foreground=self.STATUS_COLORS["PATCHED"])
        self.tree.tag_configure("ORIGINAL", foreground=self.STATUS_COLORS["ORIGINAL"])
        self.tree.tag_configure("MISSING", foreground=self.STATUS_COLORS["MISSING"])
        self.tree.tag_configure("MODIFIED", foreground=self.DEFAULT_COLOR)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Description pane (shows the selected mod's description).
        desc_frame = ttk.Frame(self.root, padding=(16, 0))
        desc_frame.pack(fill="x")
        self.desc_label = ttk.Label(desc_frame, textvariable=self.desc_var,
                                    style="Detail.TLabel", anchor="w", wraplength=730)
        self.desc_label.pack(fill="x")
        self.desc_var.set("Select a mod above to see what it does.")

        # Actions.
        actions = ttk.Frame(self.root, padding=(16, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="Patch (build)", command=self._patch).pack(side="left", padx=2)
        ttk.Button(actions, text="Apply to game", style="Accent.TButton",
                   command=self._apply).pack(side="left", padx=2)
        ttk.Button(actions, text="Revert", command=self._revert).pack(side="left", padx=2)

        # Log.
        self.log = ScrolledText(self.root, height=9, state="disabled",
                                bg=FIELD, fg=FG, insertbackground=FG,
                                relief="flat", padx=10, pady=8,
                                font=("Consolas", 9))
        self.log.pack(fill="both", expand=False, padx=16, pady=(0, 12))

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

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            self.desc_var.set("Select a mod above to see what it does.")
            return
        name = self.tree.item(sel[0], "values")[0]
        desc = next((e["desc"] for e in sm.FILES if e["title"] == name), "")
        self.desc_var.set(desc or name)

    # -- actions -----------------------------------------------------------
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        game_dir = self.game_dir_var.get()
        for name, status in sm.get_statuses(game_dir):
            tag = status if status in self.STATUS_COLORS else "MODIFIED"
            self.tree.insert("", "end", values=(name, status), tags=(tag,))
        self.desc_var.set("Select a mod above to see what it does.")

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
