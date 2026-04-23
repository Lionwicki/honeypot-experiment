"""
Shared utilities for all WAT tools.
Loads environment variables and provides common helpers.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

# Load .env from project root (works regardless of where script is called from)
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

console = Console()


def get_env(key: str, required: bool = True) -> str:
    """Fetch an env var, exit with a clear error if required and missing."""
    value = os.getenv(key)
    if not value and required:
        console.print(f"[bold red]Missing required env var:[/] {key}")
        console.print(f"Add it to [cyan]{ROOT / '.env'}[/]")
        sys.exit(1)
    return value or ""


def save_tmp(filename: str, content: str) -> Path:
    """Write content to .tmp/ and return the path."""
    tmp_dir = ROOT / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    path = tmp_dir / filename
    path.write_text(content, encoding="utf-8")
    console.print(f"[green]Saved:[/] {path}")
    return path


def load_tmp(filename: str) -> str:
    """Read a file from .tmp/."""
    path = ROOT / ".tmp" / filename
    if not path.exists():
        console.print(f"[red]File not found:[/] {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def banner(title: str, subtitle: str = "") -> None:
    """Print a styled banner for tool startup."""
    msg = f"[bold]{title}[/]"
    if subtitle:
        msg += f"\n[dim]{subtitle}[/]"
    console.print(Panel(msg, expand=False))
