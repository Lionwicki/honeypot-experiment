"""
test_stop_sequences.py — Verify stop sequence fix and current behaviour.

Tests the command sequence from findings.md Issue 7 + 8:
  1. cd /tmp && touch evil.sh  (split → two calls)
  2. ls /tmp
  3. whoami

Prints raw LLM output and state delta for each call so we can see:
  - Is hallucinated follow-up content gone? (stop sequence fix)
  - Does cd /tmp return the right error / update state correctly?

Run from repo root with venv active:
    python implementation_suggestion/test_stop_sequences.py
"""

import sys
import re
import logging

# Make the honeypot package importable from project root
sys.path.insert(0, "implementation_suggestion")

from honeypot.session_state import SessionState
from honeypot.prompt_builder import build_prompt
from honeypot.ollama_backend import query_ollama

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("test_stop_sequences")

SEPARATOR = "─" * 60


def split_commands(line: str) -> list[str]:
    parts = re.split(r"(?<!['\"])\s*(?:&&|\|\||;|\|)\s*(?!['\"])", line)
    return [p.strip() for p in parts if p.strip()]


def run_command(state: SessionState, command: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"COMMAND: $ {command}")
    sub_cmds = split_commands(command)
    if len(sub_cmds) > 1:
        print(f"  → split into {len(sub_cmds)} sub-commands: {sub_cmds}")

    for sub in sub_cmds:
        print(f"\n  [sub] $ {sub}")
        prompt = build_prompt(state, sub)
        output, delta = query_ollama(prompt)

        print(f"  RAW OUTPUT:\n{output!r}")
        print(f"  STATE DELTA: {delta}")

        state.apply_state_delta(delta)
        state.record(sub, output)

    print(f"\n  State after: cwd={state.cwd!r}  /tmp contents={state.filesystem.get('/tmp', [])!r}")


def main():
    from honeypot.ollama_backend import DEFAULT_MODEL
    print("=" * 60)
    print(f"Stop sequences smoke test — model: {DEFAULT_MODEL}")
    print("=" * 60)

    state = SessionState()

    # Test 1: chained command (the previous timeout case)
    run_command(state, "cd /tmp && touch evil.sh")

    # Test 2: ls /tmp — should show evil.sh if state delta applied correctly
    run_command(state, "ls /tmp")

    # Test 3: whoami — simple, was working before; regression check
    run_command(state, "whoami")

    print(f"\n{SEPARATOR}")
    print("DONE. Check output above:")
    print("  ✓ No hallucinated follow-up commands in RAW OUTPUT?")
    print("  ✓ State delta applied (evil.sh in /tmp)?")
    print("  ✓ cd /tmp error gone (or correctly handled)?")


if __name__ == "__main__":
    main()
