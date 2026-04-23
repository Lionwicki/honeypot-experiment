"""
ollama_backend.py — HTTP client for the local Ollama inference server.

Ollama must be running locally: https://ollama.com
Pull a model first:  ollama pull llama3.1:8b

The response is split on the ||| delimiter to separate:
  - clean terminal output  (sent to attacker)
  - state delta JSON       (consumed by SessionState)
"""

import json
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"

# NOTE: gemma3:4b is used here for local testing only (it's what's installed on this machine).
# For a real evaluation use a stronger model — recommended: llama3.1:8b or mistral:7b.
# gemma3:4b will likely break character more often and handle complex commands less reliably.
# Switch by changing this line or passing model= explicitly to query_ollama().
DEFAULT_MODEL = "llama3.2:3b"  # gemma3:4b was too slow (106s prompt ingestion); llama3.2:3b fits in RAM and has better instruction following


def query_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 240,  # llama3.2:3b cold start + history context can take 120-180s; 240s is safe ceiling
) -> tuple[str, Optional[dict]]:
    """
    Send a prompt to Ollama and return (clean_output, state_delta).

    clean_output  — the terminal text to send back to the attacker
    state_delta   — parsed JSON dict from the ||| line, or None on parse failure
    """
    start = time.monotonic()

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,    # low = more deterministic shell behaviour
                    "top_p": 0.9,
                    "num_predict": 512,    # cap output length
                    # Stop sequences: catch hallucinated shell prompts before they land in output.
                    # "\n$ " catches standard bash continuation; "\n# " catches root/BusyBox prompts.
                    # The parser also strips prompt-like lines defensively (see _parse_response).
                    "stop": ["\n$ ", "\n# ", "\n$"],
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.error("Ollama request timed out after %ds", timeout)
        return "bash: command timed out\n", None
    except requests.exceptions.ConnectionError:
        logger.error("Cannot reach Ollama at %s — is it running?", OLLAMA_URL)
        return "bash: internal error\n", None

    elapsed = time.monotonic() - start
    logger.debug("Ollama response in %.2fs", elapsed)

    raw = resp.json().get("response", "")
    return _parse_response(raw)


def _parse_response(raw: str) -> tuple[str, Optional[dict]]:
    """
    Split the LLM response on the ||| delimiter.

    Expected format:
        <terminal output lines>
        |||{"cwd": null, "new_files": {}, ...}
    """
    if "|||" not in raw:
        # LLM didn't follow the format — return raw output, no state update
        logger.warning("LLM response missing ||| delimiter — no state update applied")
        return raw.strip(), None

    parts = raw.split("|||", maxsplit=1)
    clean_output = parts[0].rstrip()

    # Defensive: strip hallucinated prompt strings that models include in output.
    import re
    # Remove any line that looks like a shell prompt: "user@host:/path[# $]*"
    # (?m) = multiline — ^ and $ match each line boundary so this catches
    # leading lines, trailing lines, and standalone prompt-only responses.
    clean_output = re.sub(
        r'(?m)^[\w][\w\-]*@[\w][\w\-]*:[^\n]*[#$]?\s*$',
        '',
        clean_output,
    ).strip()
    # Trailing hallucinated command continuations ("\n$ cmd", "\n# cmd", "\n$$ cmd").
    clean_output = re.sub(r'\n\$+\s.*$', '', clean_output, flags=re.DOTALL).strip()
    clean_output = re.sub(r'\n#+\s.*$', '', clean_output, flags=re.DOTALL).strip()

    # Strip markdown fences and other trailing junk smaller models append after the JSON
    delta_str = parts[1].strip()
    brace_end = delta_str.rfind("}")
    if brace_end != -1:
        delta_str = delta_str[: brace_end + 1]

    try:
        delta = json.loads(delta_str)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse state delta JSON: %s | raw: %r", e, delta_str)
        delta = None

    return clean_output, delta
