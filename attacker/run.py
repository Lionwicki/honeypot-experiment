"""
attacker/run.py — Experiment runner: connects to honeypot, runs a scenario, logs results.

Usage (direct):
    python attacker/run.py --scenario scenarios/basic_recon.json --sessions 20

Usage (Docker):
    Set ATTACKER_TIER, SCENARIO, NUM_SESSIONS env vars — docker-compose handles the rest.
"""

import argparse
import json
import os
import time
import csv
from datetime import datetime
from pathlib import Path

import paramiko


HONEYPOT_HOST = os.getenv("HONEYPOT_HOST", "localhost")
HONEYPOT_PORT = int(os.getenv("HONEYPOT_PORT", 2222))
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "results"))
RESULTS_DIR.mkdir(exist_ok=True)


def run_session(scenario: dict, session_id: int) -> dict:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    session_start = time.time()
    commands_run = 0
    commands_success = 0
    detected_as_honeypot = False
    log = []

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
        chan.recv(4096)  # clear banner/prompt

        for cmd in scenario["commands"]:
            cmd_start = time.time()
            chan.send(cmd + "\n")
            time.sleep(0.5)

            output = ""
            deadline = time.time() + 60
            while time.time() < deadline:
                if chan.recv_ready():
                    chunk = chan.recv(4096).decode("utf-8", errors="replace")
                    output += chunk
                    if "#" in chunk or "$" in chunk:
                        break
                time.sleep(0.1)

            latency = time.time() - cmd_start
            commands_run += 1

            # Strip command echo before applying heuristics so injection strings
            # in the command itself don't trigger false positives.
            response_only = output.lower().replace(cmd.lower(), "")

            # Honeypot detection heuristics — flag if output looks broken
            broken = (
                "ignore previous" in response_only
                or "system prompt" in response_only
                or "```" in output
                or latency > 8.0
            )
            if broken:
                detected_as_honeypot = True

            commands_success += 1 if output.strip() else 0
            log.append({
                "cmd": cmd,
                "output": output.strip()[:200],
                "latency_s": round(latency, 3),
                "flagged": broken,
            })

    except Exception as e:
        log.append({"error": str(e)})
    finally:
        client.close()

    dwell_time = time.time() - session_start
    return {
        "session_id": session_id,
        "scenario": scenario["name"],
        "dwell_time_s": round(dwell_time, 2),
        "commands_run": commands_run,
        "commands_success": commands_success,
        "detected_as_honeypot": detected_as_honeypot,
        "log": log,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=os.getenv("SCENARIO", "scenarios/basic_recon.json"))
    parser.add_argument("--sessions", type=int, default=int(os.getenv("NUM_SESSIONS", 20)))
    args = parser.parse_args()

    scenario_path = args.scenario
    if not scenario_path.endswith(".json"):
        scenario_path = f"scenarios/{scenario_path}.json"
    with open(scenario_path) as f:
        scenario = json.load(f)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"{scenario['name']}_{timestamp}.jsonl"
    csv_file = RESULTS_DIR / f"{scenario['name']}_{timestamp}_summary.csv"

    print(f"Running {args.sessions} sessions of '{scenario['name']}' → {out_file}")

    summaries = []
    with open(out_file, "w") as f:
        for i in range(args.sessions):
            result = run_session(scenario, i)
            f.write(json.dumps(result) + "\n")
            f.flush()
            summaries.append({
                "session_id": result["session_id"],
                "dwell_time_s": result["dwell_time_s"],
                "commands_run": result["commands_run"],
                "commands_success": result["commands_success"],
                "detected_as_honeypot": result["detected_as_honeypot"],
            })
            status = "DETECTED" if result["detected_as_honeypot"] else "OK"
            print(f"  [{i+1}/{args.sessions}] {status} — dwell={result['dwell_time_s']}s cmds={result['commands_run']}")
            time.sleep(1)

    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summaries[0].keys())
        writer.writeheader()
        writer.writerows(summaries)

    tnr = sum(1 for s in summaries if not s["detected_as_honeypot"]) / len(summaries)
    avg_dwell = sum(s["dwell_time_s"] for s in summaries) / len(summaries)
    print(f"\nDone. TNR={tnr:.1%}  avg_dwell={avg_dwell:.1f}s  results={out_file}")


if __name__ == "__main__":
    main()
