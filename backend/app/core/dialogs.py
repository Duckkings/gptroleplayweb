from __future__ import annotations

from pathlib import Path


def pick_directory(title: str) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    selected = filedialog.askdirectory(title=title)
    root.destroy()

    if not selected:
        return None
    return Path(selected)
