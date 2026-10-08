"""Shared bits: where results go, and the terminal styling."""

from __future__ import annotations

import os
import time
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel

RESULTS = Path(__file__).resolve().parent.parent / "results"
console = Console(highlight=False)


def replace_file(tmp: Path, out: Path) -> None:
    """os.replace, but patient on Windows, where it fails while the dashboard is reading the file.
    If the file stays busy, skip this update; the next one comes a moment later."""
    for _ in range(20):
        try:
            os.replace(tmp, out)
            return
        except PermissionError:
            time.sleep(0.05)


def header(title: str, subtitle: str) -> None:
    console.print()
    console.print(Panel(f"[dim]{subtitle}[/]", title=f"[bold #8b7bff]{title}[/]", title_align="left",
                        border_style="#3a3f5c", box=box.ROUNDED, padding=(0, 2)))
