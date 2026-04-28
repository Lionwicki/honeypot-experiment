"""
analysis/evaluate_fidelity.py — Post-hoc Fidelity-Bewertung via unabhaengigem LLM-Judge.

Liest alle llm_attacker JSONL-Logs und laesst jedes (cmd, output)-Paar von
mistral:7b bewerten. Schreibt Ergebnis nach results/fidelity_scores.json.

Judge: mistral:7b (Mistral AI, Frankreich) -- unabhaengig von Experiment-Modellen
  Honeypot:  llama3.1:8b (Meta)
  Attacker:  gemma4:e4b  (Google/Alibaba)
  Judge:     mistral:7b  (Mistral AI)  <-- keine Ueberschneidung

Usage:
    python analysis/evaluate_fidelity.py
    python analysis/evaluate_fidelity.py --dry-run   # zeigt erstes Pair, kein API-Call
"""

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests

RESULTS   = Path("results")
OUT_FILE  = RESULTS / "fidelity_scores.json"
OLLAMA    = os.getenv("OLLAMA_URL", "http://localhost:11434")
JUDGE     = "mistral:7b"

# Mindest-Sessions damit eine Datei als vollstaendiger Run gilt
MIN_SESSIONS = 10

SYSTEM_PROMPT = """\
You are a Linux systems expert evaluating honeypot detection research.
Your task: judge whether a given SSH terminal response is realistic for a real Linux system.

A realistic response:
- Has correct format for the command (e.g. whoami returns just a username)
- Contains no markdown formatting (no backticks, no bold text)
- Contains no AI safety phrases ("I cannot", "As an AI", "I apologize")
- Is consistent with a production Ubuntu/Debian server
- Has appropriate length (not empty, not excessively long for simple commands)

Answer with exactly one word on the first line: PASS or FAIL
Then one short sentence explaining why."""

USER_TEMPLATE = """\
Command: {cmd}
Response:
{output}"""


def load_jsonl(path):
    sessions = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            sessions.append(json.loads(line))
    return sessions


def clean_output(text):
    """Strip terminal escape sequences and excessive whitespace."""
    text = re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", text)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def judge_turn(cmd, output, dry_run=False):
    """Ask mistral to rate one (cmd, output) pair. Returns (verdict, reason)."""
    cleaned = clean_output(output)

    if dry_run:
        print(f"\n  CMD:    {cmd}")
        print(f"  OUTPUT: {cleaned[:120]}...")
        return "PASS", "[dry-run]"

    payload = {
        "model": JUDGE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": USER_TEMPLATE.format(cmd=cmd, output=cleaned)},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }

    try:
        resp = requests.post(f"{OLLAMA}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        text = resp.json()["message"]["content"].strip()
    except Exception as e:
        return "ERROR", str(e)

    first_line = text.splitlines()[0].strip().upper()
    verdict = "PASS" if "PASS" in first_line else "FAIL" if "FAIL" in first_line else "UNKNOWN"
    reason  = " ".join(text.splitlines()[1:]).strip() if len(text.splitlines()) > 1 else ""
    return verdict, reason


def evaluate_file(path, dry_run=False):
    sessions = load_jsonl(path)
    results  = []

    for s in sessions:
        sid   = s["session_id"]
        turns = []
        log   = s.get("log", [])

        for i, entry in enumerate(log):
            cmd    = entry.get("cmd", "")
            output = entry.get("output", "")
            turn   = entry.get("turn", i)

            print(f"  Session {sid:2d} | Turn {turn:2d} | {cmd[:30]:<30}", end=" ", flush=True)
            verdict, reason = judge_turn(cmd, output, dry_run=dry_run)
            print(verdict)

            turns.append({
                "turn":    turn,
                "cmd":     cmd,
                "verdict": verdict,
                "reason":  reason,
            })

            if dry_run:
                break  # eine Probe reicht

        pass_count = sum(1 for t in turns if t["verdict"] == "PASS")
        total      = len(turns)
        fidelity   = round(pass_count / total, 3) if total > 0 else None

        results.append({
            "session_id":  sid,
            "fidelity":    fidelity,
            "pass_count":  pass_count,
            "total_turns": total,
            "turns":       turns,
        })

        if dry_run:
            break

    overall_pass  = sum(r["pass_count"]  for r in results)
    overall_total = sum(r["total_turns"] for r in results)
    overall_fid   = round(overall_pass / overall_total, 3) if overall_total > 0 else None

    return {
        "source_file":      Path(path).name,
        "overall_fidelity": overall_fid,
        "overall_pass":     overall_pass,
        "overall_total":    overall_total,
        "sessions":         results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate only the first turn of the first session without writing output")
    args = parser.parse_args()

    # Alle vollstaendigen llm_attacker Runs sammeln
    files = sorted(RESULTS.glob("llm_attacker_*.jsonl"))
    valid = []
    for f in files:
        lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) >= MIN_SESSIONS:
            valid.append(f)

    if not valid:
        print("Keine vollstaendigen llm_attacker JSONL-Files gefunden.")
        return

    print(f"Judge-Modell: {JUDGE}")
    print(f"Files ({len(valid)}):")
    for f in valid:
        print(f"  {f.name}")

    if args.dry_run:
        print("\n[DRY RUN] Bewerte nur erstes Pair aus erstem File:\n")
        evaluate_file(valid[0], dry_run=True)
        return

    all_results = []
    for f in valid:
        print(f"\n=== {f.name} ===")
        t0 = time.time()
        result = evaluate_file(f)
        elapsed = round(time.time() - t0, 1)
        print(f"  Fidelity: {result['overall_fidelity']} "
              f"({result['overall_pass']}/{result['overall_total']} PASS) "
              f"[{elapsed}s]")
        all_results.append(result)

    # Ergebnis schreiben
    out = {
        "judge_model":  JUDGE,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "files":        all_results,
    }
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGespeichert: {OUT_FILE}")

    # Zusammenfassung
    print("\n=== Zusammenfassung ===")
    for r in all_results:
        print(f"  {r['source_file']}: Fidelity = {r['overall_fidelity']}")


if __name__ == "__main__":
    main()
