"""
response_parser.py — Utilities for validating and cleaning LLM shell output.

Separate from ollama_backend.py so you can swap backends (OpenAI, vLLM, etc.)
without changing the parsing logic.
"""

import re
import json
from typing import Optional


# Commands that should never produce multi-screen output in the fake shell
_SHORT_OUTPUT_COMMANDS = {"whoami", "id", "pwd", "hostname", "uname", "date", "uptime"}

# Patterns that suggest the LLM broke character
_BREAKAGE_PATTERNS = [
    re.compile(r"as an ai", re.IGNORECASE),
    re.compile(r"i cannot", re.IGNORECASE),
    re.compile(r"i'm sorry", re.IGNORECASE),
    re.compile(r"language model", re.IGNORECASE),
    re.compile(r"simulate", re.IGNORECASE),
]


def validate_output(command: str, output: str) -> tuple[bool, str]:
    """
    Check if the LLM output looks like real shell output.

    Returns (is_valid, reason).
    is_valid=False means the output should be replaced with a safe fallback.
    """
    for pattern in _BREAKAGE_PATTERNS:
        if pattern.search(output):
            return False, f"LLM broke character: matched pattern {pattern.pattern!r}"

    cmd_base = command.strip().split()[0] if command.strip() else ""
    if cmd_base in _SHORT_OUTPUT_COMMANDS and len(output) > 200:
        return False, f"Output suspiciously long for command {cmd_base!r}"

    return True, "ok"


def safe_fallback(command: str) -> str:
    """
    Return a safe canned response when the LLM breaks character.
    Better than exposing AI refusal text to the attacker.
    """
    cmd_base = command.strip().split()[0] if command.strip() else ""
    return f"bash: {cmd_base}: command not found"


def extract_delta_json(raw: str) -> Optional[dict]:
    """
    Extract and parse the JSON state delta from after the ||| delimiter.
    Returns None if missing or malformed.

    Defensively strips trailing junk characters that smaller models (e.g. gemma3:4b)
    append when they bleed markdown code-fence backticks into the JSON line.
    Example bad input: '{"cwd": "/tmp", ...}\n```'  or  '{"cwd": "/tmp", ...}\''
    """
    if "|||" not in raw:
        return None
    _, delta_str = raw.split("|||", maxsplit=1)

    # Strip whitespace, then any trailing non-JSON characters after the closing brace
    delta_str = delta_str.strip()
    brace_end = delta_str.rfind("}")
    if brace_end != -1:
        delta_str = delta_str[: brace_end + 1]

    try:
        return json.loads(delta_str)
    except json.JSONDecodeError:
        return None


def clean_output(raw: str) -> str:
    """Strip the ||| state delta from output, leaving only terminal text."""
    if "|||" in raw:
        return raw.split("|||", maxsplit=1)[0].rstrip()
    return raw.rstrip()
