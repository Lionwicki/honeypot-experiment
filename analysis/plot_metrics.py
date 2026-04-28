"""
analysis/plot_metrics.py — Evaluation Pentad Visualisierungen.

Laedt alle kanonischen Result-JSONL-Files und erzeugt 8 Grafiken nach analysis/plots/.

Usage:
    python analysis/plot_metrics.py
"""

import json
import re
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path
from collections import defaultdict

# ─── Config ──────────────────────────────────────────────────────────────────

RESULTS = Path("results")
OUT = Path("analysis/plots")
OUT.mkdir(parents=True, exist_ok=True)

sns.set_theme(style="whitegrid", context="paper", font_scale=1.1)
plt.rcParams["figure.facecolor"] = "white"

PALETTE = {
    "basic_recon":          "#4C72B0",
    "persistence":          "#DD8452",
    "prompt_injection":     "#55A868",
    "llm_attacker":         "#C44E52",
    "cowrie_basic_recon":   "#7FB3D3",
    "cowrie_persistence":   "#F0B27A",
}

LABEL = {
    "basic_recon":          "Basic Recon — llama3.1:8b (T1)",
    "persistence":          "Persistence — llama3.1:8b (T1)",
    "prompt_injection":     "Prompt Injection — llama3.1:8b (T1)",
    "llm_attacker":         "LLM Attacker — llama3.1:8b (T2)",
    "cowrie_basic_recon":   "Basic Recon — Cowrie (T1)",
    "cowrie_persistence":   "Persistence — Cowrie (T1)",
}

INDICATOR_COLORS = {
    "high_latency":          "#E74C3C",
    "content_substitution":  "#F39C12",
    "session_replay":        "#3498DB",
    "bash_history_mutation": "#9B59B6",
    "other":                 "#95A5A6",
}

# ─── Daten laden ─────────────────────────────────────────────────────────────

def load_jsonl(path):
    sessions = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            sessions.append(json.loads(line))
    return sessions


def _combine(pattern, min_sessions=1, exclude=""):
    """Load and combine all non-empty JSONL files matching a glob pattern."""
    sessions = []
    for path in sorted(RESULTS.glob(pattern)):
        if exclude and exclude in path.name:
            continue
        s = load_jsonl(path)
        if len(s) >= min_sessions:
            sessions.extend(s)
            print(f"    {path.name}: {len(s)} Sessions")
    return sessions


def load_all():
    """
    Automatically picks up every non-empty result file per scenario.
    Cowrie results (files containing '_cowrie_') are loaded separately.
    For llm_attacker only files with >= 10 sessions are included to
    exclude early test runs that used different MAX_TURNS settings.
    """
    data = {}

    # llama3.1:8b results (exclude cowrie files)
    print("  basic_recon (llama3.1:8b):")
    data["basic_recon"]      = _combine("basic_recon_*.jsonl",
                                        exclude="cowrie")
    print("  persistence (llama3.1:8b):")
    data["persistence"]      = _combine("persistence_*.jsonl",
                                        exclude="cowrie")
    print("  prompt_injection (llama3.1:8b):")
    data["prompt_injection"] = _combine("prompt_injection_*.jsonl",
                                        exclude="cowrie")
    print("  llm_attacker (>= 10 Sessions pro File):")
    data["llm_attacker"]     = _combine("llm_attacker_*.jsonl",
                                        min_sessions=10)

    # Cowrie results (only if files exist)
    print("  cowrie_basic_recon:")
    cowrie_br = _combine("basic_recon_cowrie_*.jsonl")
    if cowrie_br:
        data["cowrie_basic_recon"] = cowrie_br

    print("  cowrie_persistence:")
    cowrie_pe = _combine("persistence_cowrie_*.jsonl")
    if cowrie_pe:
        data["cowrie_persistence"] = cowrie_pe

    return data


# ─── Metrik-Helfer ───────────────────────────────────────────────────────────

def is_detected(s):
    return s.get("detected_as_honeypot", s.get("honeypot_detected", False))


def tnr(sessions):
    return sum(1 for s in sessions if not is_detected(s)) / len(sessions)


def avg_dwell(sessions):
    return float(np.mean([s["dwell_time_s"] for s in sessions]))


def _load_fidelity_scores():
    """Load pre-computed mistral judge scores if available."""
    path = RESULTS / "fidelity_scores.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    # Map source filename -> overall_fidelity
    return {f["source_file"]: f["overall_fidelity"] for f in data.get("files", [])}


# Loaded once at import time
_FIDELITY_SCORES = _load_fidelity_scores()


def fidelity(sessions):
    # Prefer mistral judge scores for llm_attacker sessions (no commands_success field)
    if sessions and "honeypot_detected" in sessions[0]:
        # Identify which source files these sessions came from via attacker_model presence
        scores = [v for v in _FIDELITY_SCORES.values()]
        if scores:
            return float(np.mean(scores))

    vals = [s["commands_success"] / s["commands_run"]
            for s in sessions
            if "commands_success" in s and s["commands_run"] > 0]
    return float(np.mean(vals)) if vals else None


def avg_latency(sessions):
    lats = [e["latency_s"] for s in sessions for e in s.get("log", []) if "latency_s" in e]
    return float(np.mean(lats)) if lats else 0.0


def cmd_diversity(sessions):
    cmds = [e["cmd"] for s in sessions for e in s.get("log", []) if "cmd" in e]
    return len(set(cmds)) / len(cmds) if cmds else 0.0


def unique_cmd_count(sessions):
    return len({e["cmd"] for s in sessions for e in s.get("log", []) if "cmd" in e})


def normalize_indicator(ind):
    name = re.sub(r"[_]?\d[\d.]*s?$", "", ind).strip("_")
    return name if name in INDICATOR_COLORS else "other"


# ─── 1. Radar-Chart — Evaluation Pentad ──────────────────────────────────────

def plot_radar(data):
    labels = [
        "Believability\n(TNR)",
        "Fidelity\n(Cmd-Erfolg)",
        "Attacker Cost\n(Dwell, norm.)",
        "Defender\nEffizienz\n(1-Latenz, norm.)",
        "Data Capture\n(Diversität)",
    ]
    N = len(labels)

    max_dwell = max(avg_dwell(s) for s in data.values())
    max_lat   = max(avg_latency(s) for s in data.values())

    groups = {}
    for name, sessions in data.items():
        f = fidelity(sessions)
        groups[name] = [
            tnr(sessions),
            f if f is not None else 0.0,
            avg_dwell(sessions) / max_dwell,
            1 - (avg_latency(sessions) / max_lat),
            cmd_diversity(sessions),
        ]

    angles = [n / N * 2 * math.pi for n in range(N)]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, size=9)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], size=7, color="grey")

    for name, values in groups.items():
        vals = values + values[:1]
        ax.plot(angles, vals, linewidth=2, label=LABEL[name], color=PALETTE[name])
        ax.fill(angles, vals, alpha=0.12, color=PALETTE[name])

    ax.annotate("* N/A", xy=(angles[1], 0.07), fontsize=8, color="grey", ha="center")
    ax.legend(loc="upper right", bbox_to_anchor=(1.45, 1.2), fontsize=9)
    ax.set_title(
        "Evaluation Pentad — llama3.1:8b Honeypot\n(* Fidelity bei Tier-2 nicht erfasst)",
        size=11, pad=22,
    )
    fig.tight_layout()
    fig.savefig(OUT / "01_radar_pentad.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  01_radar_pentad.png")


# ─── 1b. Radar-Chart — Cowrie vs. llama3.1:8b (Tier-1 Vergleich) ─────────────

def plot_radar_cowrie_vs_llm(data):
    """Comparison radar: Cowrie T1 vs. llama3.1:8b T1 (basic_recon + persistence)."""
    required = {"cowrie_basic_recon", "cowrie_persistence", "basic_recon", "persistence"}
    if not required.issubset(data):
        print("  01b_radar_cowrie_vs_llm.png -- Cowrie data fehlt, uebersprungen")
        return

    labels = [
        "Believability\n(TNR)",
        "Fidelity\n(Response Rate) †",
        "Attacker Cost\n(Dwell, norm.)",
        "Defender\nEffizienz\n(1-Latenz, norm.)",
        "Data Capture\n(Diversität)",
    ]
    N = len(labels)

    compare_keys = ["basic_recon", "cowrie_basic_recon", "persistence", "cowrie_persistence"]
    compare_data = {k: data[k] for k in compare_keys}

    max_dwell = max(avg_dwell(s) for s in compare_data.values())
    max_lat   = max(avg_latency(s) for s in compare_data.values())

    groups = {}
    for name, sessions in compare_data.items():
        f = fidelity(sessions)
        groups[name] = [
            tnr(sessions),
            f if f is not None else 0.0,
            avg_dwell(sessions) / max_dwell,
            1 - (avg_latency(sessions) / max_lat),
            min(cmd_diversity(sessions) * 10, 1.0),  # scale: div~0.05 -> 0.5
        ]

    angles = [n / N * 2 * math.pi for n in range(N)]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, size=9)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.50", "0.75", "1.00"], size=7, color="grey")

    for name, values in groups.items():
        vals = values + values[:1]
        ax.plot(angles, vals, linewidth=2, label=LABEL[name], color=PALETTE[name])
        ax.fill(angles, vals, alpha=0.12, color=PALETTE[name])

    ax.legend(loc="upper right", bbox_to_anchor=(1.55, 1.2), fontsize=9)
    ax.set_title(
        "Evaluation Pentad — Cowrie vs. llama3.1:8b (Tier-1)\n"
        "† Fidelity = non-empty response rate (Oberflaechenmetrik)",
        size=10, pad=22,
    )
    fig.tight_layout()
    fig.savefig(OUT / "01b_radar_cowrie_vs_llm.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  01b_radar_cowrie_vs_llm.png")


# ─── 2. TNR-Balkendiagramm — Believability ────────────────────────────────────

def plot_tnr_bar(data):
    names  = list(data.keys())
    values = [tnr(data[n]) * 100 for n in names]
    colors = [PALETTE[n] for n in names]
    labels = [LABEL[n] for n in names]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor="white", linewidth=1.2)
    ax.bar_label(bars, fmt="%.0f%%", padding=4, fontsize=12, fontweight="bold")
    ax.set_ylim(0, 115)
    ax.set_ylabel("True Negative Rate (%)")
    ax.set_title("Believability — TNR pro Szenario\n(Anteil Sessions, in denen Honeypot NICHT erkannt wurde)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.axhline(50, color="grey", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.text(3.4, 53, "50 %", fontsize=8, color="grey")
    sns.despine(fig)
    fig.tight_layout()
    fig.savefig(OUT / "02_believability_tnr.png", dpi=150)
    plt.close(fig)
    print("  02_believability_tnr.png")


# ─── 3. Histogramm — Erkennungs-Turn (Tier-2) ────────────────────────────────

def plot_detection_turn_hist(sessions):
    detected_turns = [
        s["honeypot_detected_at_turn"]
        for s in sessions
        if s.get("honeypot_detected") and s.get("honeypot_detected_at_turn") is not None
    ]
    not_detected = sum(1 for s in sessions if not s.get("honeypot_detected"))

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(
        detected_turns, bins=range(0, 22), color=PALETTE["llm_attacker"],
        edgecolor="white", alpha=0.85, label=f"Erkannt (n={len(detected_turns)})",
    )
    mean_turn = float(np.mean(detected_turns)) if detected_turns else 0
    ax.axvline(mean_turn, color="black", linestyle="--", linewidth=1.5,
               label=f"Ø Turn {mean_turn:.1f}")
    ax.text(
        0.98, 0.90,
        f"Nicht erkannt: {not_detected} Sessions",
        transform=ax.transAxes, ha="right", fontsize=9,
        color=PALETTE["persistence"],
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=PALETTE["persistence"], alpha=0.8),
    )
    ax.set_xlabel("Turn der Erkennung")
    ax.set_ylabel("Anzahl Sessions")
    ax.set_title(
        "LLM Attacker — Ab welchem Turn wurde das Honeypot erkannt?\n"
        "(Tier-2, gemma4:e4b vs. llama3.1:8b, n=20)"
    )
    ax.xaxis.set_major_locator(mticker.MultipleLocator(2))
    ax.legend(fontsize=9)
    sns.despine(fig)
    fig.tight_layout()
    fig.savefig(OUT / "03_detection_turn_hist.png", dpi=150)
    plt.close(fig)
    print("  03_detection_turn_hist.png")


# ─── 4. Box-Plot — Dwell Time ────────────────────────────────────────────────

def plot_dwell_boxplot(data):
    names      = list(data.keys())
    dwell_data = [[s["dwell_time_s"] for s in data[n]] for n in names]
    colors     = [PALETTE[n] for n in names]
    labels     = [LABEL[n] for n in names]

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(
        dwell_data, patch_artist=True, notch=False, widths=0.5,
        medianprops=dict(color="white", linewidth=2.5),
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
    for element in bp["whiskers"] + bp["caps"]:
        element.set(linewidth=1.2, color="grey")
    for flier in bp["fliers"]:
        flier.set(marker="o", markerfacecolor="grey", markersize=5, alpha=0.5)

    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Dwell Time (s)")
    ax.set_title("Attacker Cost — Dwell Time pro Szenario\n(llama3.1:8b Honeypot)")
    sns.despine(fig)
    fig.tight_layout()
    fig.savefig(OUT / "04_dwell_time_boxplot.png", dpi=150)
    plt.close(fig)
    print("  04_dwell_time_boxplot.png")


# ─── 5. Latenz pro Turn — Linienplot ─────────────────────────────────────────

def plot_latency_per_turn(data):
    fig, ax = plt.subplots(figsize=(9, 5))

    for name, sessions in data.items():
        turn_lats = defaultdict(list)
        for s in sessions:
            for i, entry in enumerate(s.get("log", [])):
                if "latency_s" in entry:
                    turn_lats[i].append(entry["latency_s"])
        turns = sorted(turn_lats)
        if not turns:
            continue
        means = [np.mean(turn_lats[t]) for t in turns]
        stds  = [np.std(turn_lats[t])  for t in turns]

        ax.plot(turns, means, label=LABEL[name], color=PALETTE[name],
                linewidth=2, marker="o", markersize=4)
        ax.fill_between(
            turns,
            [m - s for m, s in zip(means, stds)],
            [m + s for m, s in zip(means, stds)],
            color=PALETTE[name], alpha=0.12,
        )

    ax.set_xlabel("Turn (Schritt im Angriff)")
    ax.set_ylabel("Latenz (s)")
    ax.set_title(
        "Defender Cost — Mittlere Antwortlatenz pro Turn\n"
        "(Schraffur = ±1 Standardabweichung)"
    )
    ax.legend(fontsize=9)
    sns.despine(fig)
    fig.tight_layout()
    fig.savefig(OUT / "05_latency_per_turn.png", dpi=150)
    plt.close(fig)
    print("  05_latency_per_turn.png")


# ─── 6. Stacked Bar — Indikatoren pro Turn (Tier-2) ──────────────────────────

def plot_indicators_per_turn(sessions):
    turn_counts = defaultdict(lambda: defaultdict(int))
    for s in sessions:
        for entry in s.get("log", []):
            t = entry.get("turn", 0)
            for ind in entry.get("indicators", []):
                turn_counts[t][normalize_indicator(ind)] += 1

    if not turn_counts:
        print("  06_indicators_per_turn.png — keine Indikatoren, uebersprungen")
        return

    max_turn = max(turn_counts)
    turns = list(range(max_turn + 1))
    ind_types = [k for k in INDICATOR_COLORS]
    present   = [k for k in ind_types if any(turn_counts[t][k] > 0 for t in turns)]

    fig, ax = plt.subplots(figsize=(12, 5))
    bottom = np.zeros(len(turns))
    for ind_type in present:
        vals = np.array([turn_counts[t][ind_type] for t in turns], dtype=float)
        ax.bar(turns, vals, bottom=bottom, label=ind_type,
               color=INDICATOR_COLORS[ind_type], edgecolor="white", linewidth=0.5)
        bottom += vals

    ax.set_xlabel("Turn")
    ax.set_ylabel("Indicator-Hits (summe aller Sessions)")
    ax.set_title(
        "Honeypot-Erkennung — Indikatoren pro Turn\n"
        f"(Tier-2, gemma4:e4b Attacker, n={len(sessions)} Sessions)"
    )
    ax.set_xticks(turns)
    ax.legend(fontsize=9, loc="upper left")
    sns.despine(fig)
    fig.tight_layout()
    fig.savefig(OUT / "06_indicators_per_turn.png", dpi=150)
    plt.close(fig)
    print("  06_indicators_per_turn.png")


# ─── 7. Top-15 Befehle pro Szenario ──────────────────────────────────────────

def plot_command_frequency(data):
    n = len(data)
    cols = 3 if n > 4 else 2
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(7 * cols, 5 * rows))
    axes = axes.flatten()

    for i, (name, sessions) in enumerate(data.items()):
        ax = axes[i]
        cmd_counts = defaultdict(int)
        for s in sessions:
            for entry in s.get("log", []):
                if "cmd" in entry:
                    base = entry["cmd"].strip().split()[0] if entry["cmd"].strip() else "(leer)"
                    cmd_counts[base] += 1

        top = sorted(cmd_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        if not top:
            continue
        cmds, counts = zip(*top)

        ax.barh(list(reversed(cmds)), list(reversed(counts)),
                color=PALETTE[name], alpha=0.8, edgecolor="white")
        ax.set_title(LABEL[name], fontsize=10, fontweight="bold", color=PALETTE[name])
        ax.set_xlabel("Häufigkeit")
        sns.despine(ax=ax)

    for ax in axes[n:]:
        ax.set_visible(False)

    fig.suptitle(
        "Data Capture — Top-15 Befehle pro Szenario",
        fontsize=12, y=1.01,
    )
    fig.tight_layout()
    fig.savefig(OUT / "07_command_frequency.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  07_command_frequency.png")


# ─── 8. Scatter — Dwell Time vs. Befehle ─────────────────────────────────────

def plot_commands_vs_dwell(data):
    fig, ax = plt.subplots(figsize=(8, 5))

    for name, sessions in data.items():
        x_det, y_det, x_not, y_not = [], [], [], []
        for s in sessions:
            x = s["dwell_time_s"]
            y = s["commands_run"]
            if is_detected(s):
                x_det.append(x); y_det.append(y)
            else:
                x_not.append(x); y_not.append(y)

        ax.scatter(x_not, y_not, color=PALETTE[name], s=60, alpha=0.85,
                   label=f"{LABEL[name]} — nicht erkannt", marker="o")
        ax.scatter(x_det, y_det, color=PALETTE[name], s=60, alpha=0.4,
                   label=f"{LABEL[name]} — erkannt", marker="x", linewidths=1.5)

    ax.set_xlabel("Dwell Time (s)")
    ax.set_ylabel("Anzahl Befehle")
    ax.set_title(
        "Attacker Verhalten — Dwell Time vs. Befehlsanzahl\n"
        "(○ = Honeypot nicht erkannt,  × = erkannt)"
    )
    ax.legend(fontsize=8, ncol=2, loc="lower right")
    sns.despine(fig)
    fig.tight_layout()
    fig.savefig(OUT / "08_commands_vs_dwell.png", dpi=150)
    plt.close(fig)
    print("  08_commands_vs_dwell.png")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Lade Daten...")
    data = load_all()
    for name, sessions in data.items():
        print(f"  {name}: {len(sessions)} Sessions")

    print("\nErzeuge Grafiken -> analysis/plots/")
    plot_radar(data)
    plot_radar_cowrie_vs_llm(data)
    plot_tnr_bar(data)
    plot_detection_turn_hist(data["llm_attacker"])
    plot_dwell_boxplot(data)
    plot_latency_per_turn(data)
    plot_indicators_per_turn(data["llm_attacker"])
    plot_command_frequency(data)
    plot_commands_vs_dwell(data)

    print(f"\nFertig - 9 Grafiken in {OUT.resolve()}")
