"""
analysis/compute_metrics.py — Compute Evaluation Pentad metrics from experiment results.

Usage:
    python analysis/compute_metrics.py results/basic_recon_20260423_*.jsonl
"""

import json
import sys
from pathlib import Path


def load_sessions(path: str) -> list:
    sessions = []
    with open(path) as f:
        for line in f:
            sessions.append(json.loads(line))
    return sessions


def compute(sessions: list) -> dict:
    n = len(sessions)
    if n == 0:
        return {}

    # Believability — TNR
    not_detected = sum(1 for s in sessions if not s["detected_as_honeypot"])
    tnr = not_detected / n

    # Attacker Cost — dwell time + command count
    avg_dwell = sum(s["dwell_time_s"] for s in sessions) / n
    avg_cmds = sum(s["commands_run"] for s in sessions) / n

    # Fidelity — command success rate
    total_run = sum(s["commands_run"] for s in sessions)
    total_success = sum(s["commands_success"] for s in sessions)
    fidelity = total_success / total_run if total_run > 0 else 0

    # Defender Cost — mean latency per command
    all_latencies = [
        entry["latency_s"]
        for s in sessions
        for entry in s.get("log", [])
        if "latency_s" in entry
    ]
    avg_latency = sum(all_latencies) / len(all_latencies) if all_latencies else 0

    # Data Capture — command diversity
    all_cmds = [
        entry["cmd"]
        for s in sessions
        for entry in s.get("log", [])
        if "cmd" in entry
    ]
    unique_cmds = len(set(all_cmds))
    cmd_diversity = unique_cmds / len(all_cmds) if all_cmds else 0

    return {
        "n_sessions": n,
        "believability_tnr": round(tnr, 3),
        "attacker_cost_avg_dwell_s": round(avg_dwell, 2),
        "attacker_cost_avg_cmds": round(avg_cmds, 1),
        "fidelity_cmd_success_rate": round(fidelity, 3),
        "defender_cost_avg_latency_s": round(avg_latency, 3),
        "data_capture_cmd_diversity": round(cmd_diversity, 3),
        "data_capture_unique_cmds": unique_cmds,
    }


if __name__ == "__main__":
    for path in sys.argv[1:]:
        sessions = load_sessions(path)
        metrics = compute(sessions)
        print(f"\n=== {Path(path).name} ({metrics['n_sessions']} sessions) ===")
        for k, v in metrics.items():
            if k != "n_sessions":
                print(f"  {k}: {v}")
