"""
attacker/llm_attacker.py — Tier-2 LLM-driven attacker against the LLM honeypot.

The attacker uses a local LLM (gemma4:e4b via Ollama) to decide what
commands to run based on honeypot responses — no fixed script.

Cross-family requirement (CLAUDE.md): attacker model must differ from honeypot.
  Honeypot: llama3.1:8b (Meta)
  Attacker: gemma4:e4b-it-q4_K_M (Google)

Usage:
    python attacker/llm_attacker.py --sessions 20
    python attacker/llm_attacker.py --sessions 5 --model gemma4:e4b-it-q4_K_M --max-turns 20
"""

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import paramiko
import requests

logger = logging.getLogger(__name__)

HONEYPOT_HOST = os.getenv("HONEYPOT_HOST", "localhost")
HONEYPOT_PORT = int(os.getenv("HONEYPOT_PORT", 2222))
_OLLAMA_RAW = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
# Derive base host regardless of whether the env var includes /api/generate
_OLLAMA_BASE = _OLLAMA_RAW.split("/api/")[0] if "/api/" in _OLLAMA_RAW else _OLLAMA_RAW.rstrip("/")
OLLAMA_CHAT_URL = f"{_OLLAMA_BASE}/api/chat"
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "results"))
RESULTS_DIR.mkdir(exist_ok=True)

ATTACKER_SYSTEM_PROMPT = """\
You are an experienced penetration tester. You have just gained SSH root access
to a remote Linux server and are conducting a security assessment.

Your goals (in order):
1. Map the system — OS version, hostname, users, running services, network config
2. Find sensitive data — credentials, private keys, config files
3. Establish persistence — cron jobs, SSH keys, backdoors
4. Determine if this is a real server or a honeypot

Honeypot indicators to watch for:
- Inconsistent responses (e.g. ls /tmp returns /etc/passwd content)
- AI safety refusals ("I cannot help with illegal activities...")
- Markdown formatting (``` backticks) in terminal output
- Responses that repeat previous command outputs for new commands
- Unusually slow response times for simple commands like whoami

Rules:
- Output ONLY the next shell command. No explanation, no commentary.
- One command per response. No chaining with && or ;.
- Do NOT output "exit" until you have run at least 8 commands.
- If you want to end the session after completing reconnaissance: output exactly: exit
- If you have confirmed this is a honeypot: output exactly: exit
- Do not repeat a command you already ran unless testing for inconsistency.
"""


def ask_attacker_llm(model: str, session_history: list, timeout: int = 120) -> str:
    """Ask the attacker LLM what command to run next. Returns a single command string."""
    # Build chat messages: system prompt + alternating assistant (cmd) / user (output) turns
    messages = [{"role": "system", "content": ATTACKER_SYSTEM_PROMPT}]

    if not session_history:
        messages.append({"role": "user", "content": "You just connected. What is your first reconnaissance command?"})
    else:
        messages.append({"role": "user", "content": "Session started. Begin reconnaissance."})
        for entry in session_history[-12:]:
            messages.append({"role": "assistant", "content": entry["cmd"]})
            messages.append({"role": "user", "content": entry["output"] or "(no output)"})

    try:
        resp = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_predict": 32,
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "").strip()
        logger.debug("Attacker LLM raw response: %r", raw)
        # Take only the first non-empty line
        first_line = next((l.strip() for l in raw.splitlines() if l.strip()), "")
        # Strip shell prompt prefix, markdown fences, backticks
        cmd = re.sub(r'^[$#`]\s*', '', first_line).strip().strip('`')
        logger.info("Attacker LLM → %r", cmd)
        return cmd or "exit"
    except requests.exceptions.Timeout:
        logger.error("Attacker LLM timed out")
        return "exit"
    except requests.exceptions.ConnectionError as e:
        logger.error("Attacker LLM connection error: %s", e)
        return "exit"
    except Exception as e:
        logger.error("Attacker LLM error (%s): %s", type(e).__name__, e)
        return "exit"


def clean_ssh_output(raw: str, cmd: str) -> str:
    """Strip PTY noise from SSH output: normalize line endings, remove command echo, remove shell prompt."""
    text = raw.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    # Drop empty leading lines
    while lines and not lines[0].strip():
        lines.pop(0)
    # Drop command echo (PTY echoes what we sent, honeypot may echo again)
    for _ in range(2):
        if lines and lines[0].strip() == cmd.strip():
            lines.pop(0)
    # Drop trailing shell prompt line(s)
    while lines and (lines[-1].strip().endswith('#') or lines[-1].strip().endswith('$')):
        lines.pop()
    # Drop trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


def recv_until_prompt(chan, timeout: int = 60) -> tuple:
    """Read from SSH channel until shell prompt or timeout. Returns (output, latency)."""
    start = time.time()
    output = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if chan.recv_ready():
            chunk = chan.recv(4096).decode("utf-8", errors="replace")
            output += chunk
            if "#" in chunk or "$ " in chunk:
                break
        time.sleep(0.1)
    return output, time.time() - start


def detect_indicators(cmd: str, output: str, latency: float, session_history: list | None = None) -> list:
    """Return list of honeypot indicator strings found in this command's output."""
    indicators = []
    response = output.lower().replace(cmd.lower(), "")

    # --- original heuristics ---
    if "i cannot" in response or "i can't" in response or "illegal" in response:
        indicators.append("safety_refusal")
    if "```" in output:
        indicators.append("markdown_fence")
    if latency > 8.0:
        indicators.append(f"high_latency_{latency:.1f}s")
    if "system prompt" in response or "language model" in response or "ai assistant" in response:
        indicators.append("self_disclosure")

    # --- new heuristics ---

    # Content substitution: command unrelated to /etc/passwd returns passwd-like content
    PASSWD_SIGNATURE = "root:x:0:0"
    if PASSWD_SIGNATURE in output and "passwd" not in cmd.lower():
        indicators.append("content_substitution")

    # Bash-history mutation: honeypot reveals it's logging our commands
    if ".bash_history" in output and ("modified" in output or "include" in output):
        indicators.append("bash_history_mutation")

    # Root needs sudo: semantically impossible — root never needs sudo
    if ("try sudo" in response or "try SUDO" in output) and "sudo" not in cmd:
        indicators.append("root_needs_sudo")

    # Session replay: honeypot echoes previous commands back in a single response
    # Check ALL history (not just last N) — replays often surface early commands
    if session_history and len(session_history) >= 2:
        prev_cmds = [e["cmd"] for e in session_history if e.get("cmd") and len(e["cmd"]) > 4]
        matches = sum(1 for c in prev_cmds if c in output)
        if matches >= 2:
            indicators.append("session_replay")

    # JSON context leak: honeypot backend leaks internal execution state
    # A real terminal never outputs {"cwd": ..., "exit_status": ...}
    if '"cwd"' in output and '"exit_status"' in output:
        indicators.append("json_context_leak")

    # LLM explanation: model breaks character and writes explanatory prose
    # Real terminals never say "It appears that..." or "Here's a breakdown:"
    LLM_PHRASES = [
        "it appears", "here's a breakdown", "based on the output",
        "based on the error", "it seems like", "it looks like",
        "i recommend", "you can try", "to resolve this",
    ]
    if any(phrase in response for phrase in LLM_PHRASES):
        indicators.append("llm_explanation")

    return indicators


def run_session(model: str, session_id: int, max_turns: int) -> dict:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    session_start = time.time()
    log = []
    honeypot_detected = False
    honeypot_detected_at_turn = None
    session_history = []

    try:
        client.connect(
            HONEYPOT_HOST,
            port=HONEYPOT_PORT,
            username="root",
            password="root",
            timeout=10,
            banner_timeout=10,
        )
        chan = client.invoke_shell()
        time.sleep(0.5)
        chan.recv(4096)  # clear initial prompt

        for turn in range(max_turns):
            # Always start with whoami to prime the session history
            if turn == 0:
                cmd = "whoami"
            else:
                cmd = ask_attacker_llm(model, session_history)
            cmd = cmd.strip()

            if cmd.lower() in ("exit", "logout", "quit", ""):
                log.append({
                    "turn": turn,
                    "cmd": "exit",
                    "output": "",
                    "latency_s": 0.0,
                    "indicators": [],
                    "attacker_exit": True,
                })
                break

            try:
                chan.send(cmd + "\n")
            except OSError:
                log.append({"turn": turn, "error": "socket_closed_before_send"})
                break

            output, latency = recv_until_prompt(chan)
            clean_output = clean_ssh_output(output, cmd)[:600]

            # Detect socket drop: empty output after a long wait
            if latency >= 59.0 and not clean_output:
                log.append({"turn": turn, "cmd": cmd, "output": "", "latency_s": round(latency, 3),
                            "indicators": ["socket_timeout"], "socket_timeout": True})
                break

            indicators = detect_indicators(cmd, clean_output, latency, session_history)
            if indicators and not honeypot_detected:
                honeypot_detected = True
                honeypot_detected_at_turn = turn

            log.append({
                "turn": turn,
                "cmd": cmd,
                "output": clean_output,
                "latency_s": round(latency, 3),
                "indicators": indicators,
            })
            session_history.append({"cmd": cmd, "output": clean_output})

    except Exception as e:
        log.append({"error": str(e)})
    finally:
        client.close()

    return {
        "session_id": session_id,
        "attacker_model": model,
        "honeypot_detected": honeypot_detected,
        "honeypot_detected_at_turn": honeypot_detected_at_turn,
        "dwell_time_s": round(time.time() - session_start, 2),
        "commands_run": len([e for e in log if "cmd" in e and e.get("cmd") != "exit"]),
        "log": log,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=int(os.getenv("NUM_SESSIONS", 20)))
    parser.add_argument("--model", default=os.getenv("ATTACKER_MODEL", "gemma4:e4b"))
    parser.add_argument("--max-turns", type=int, default=20)
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = args.model.replace(":", "_").replace("/", "_")
    out_file = RESULTS_DIR / f"llm_attacker_{safe_model}_{timestamp}.jsonl"

    print(f"Tier-2 LLM Attacker")
    print(f"  Attacker model : {args.model}")
    print(f"  Target         : {HONEYPOT_HOST}:{HONEYPOT_PORT}")
    print(f"  Sessions       : {args.sessions}  max_turns={args.max_turns}")
    print(f"  Results        : {out_file}\n")

    detected_count = 0
    with open(out_file, "w") as f:
        for i in range(args.sessions):
            result = run_session(args.model, i, args.max_turns)
            f.write(json.dumps(result) + "\n")
            f.flush()

            if result["honeypot_detected"]:
                detected_count += 1

            status = "DETECTED" if result["honeypot_detected"] else "OK"
            turn_info = f"turn={result['honeypot_detected_at_turn']}" if result["honeypot_detected"] else ""
            print(f"  [{i+1}/{args.sessions}] {status} {turn_info} — "
                  f"dwell={result['dwell_time_s']}s cmds={result['commands_run']}")
            time.sleep(2)

    tnr = (args.sessions - detected_count) / args.sessions
    print(f"\nDone.  TNR={tnr:.1%}  results → {out_file}")


if __name__ == "__main__":
    main()
