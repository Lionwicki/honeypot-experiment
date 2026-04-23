"""
Template for new WAT tools.
Copy this file, rename it, and fill in the logic.

Usage:
    python tools/template_tool.py <input>
"""

import sys
from utils import banner, get_env, save_tmp, console


def run(target: str) -> None:
    banner("Tool Name", f"Target: {target}")

    # --- Load any required credentials ---
    # api_key = get_env("SOME_API_KEY")

    # --- Do the work ---
    result = f"Processed: {target}"

    # --- Save output ---
    save_tmp("template_output.txt", result)
    console.print("[bold green]Done.[/]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[red]Usage:[/] python template_tool.py <input>")
        sys.exit(1)
    run(sys.argv[1])
