# CLAUDE.md

## Project Context

**Honeypot Experiment** — controlled evaluation of traditional vs. LLM-based SSH honeypots.

This repo is the implementation and experiment infrastructure for a DHBW Studienarbeit comparing Cowrie (traditional) vs. LLM-based honeypots (llama3.1:8b local, cloud API) using the Evaluation Pentad framework (adapted from Bridges et al. 2025).

**Thesis repo:** `../studienarbeit-honeypot` — writing lives there, not here.

### Evaluation Pentad (5 axes)
1. **Believability** — TNR: did the attacker detect the honeypot?
2. **Fidelity** — command success rate, state consistency
3. **Attacker Cost** — dwell time, commands per session
4. **Defender Cost** — response latency, deployment complexity
5. **Data Capture** — command diversity, semantic interaction depth

### Architecture

```
Windows Host
├── Ollama (native, GPU via DirectML)        port 11434
└── Docker Desktop
    ├── honeypot container                   port 2222
    │   └── connects to Ollama at host.docker.internal:11434
    └── attacker container (experiment only)
        └── runs scenarios against honeypot
```

### Hardware
| Machine | CPU | RAM | GPU | Use |
|---------|-----|-----|-----|-----|
| Desktop A | i5-13400F | 32 GB | RX 7900 XT (20 GB) | Primary — llama3.1:8b GPU |
| Desktop B | Ryzen 7 9800X3D | 32 GB | — | CPU fallback |
| Dev laptop | i5-7300U | 7.6 GB | — | Cowrie baseline only |

### Experiment Design
- **Tier 1:** Scripted bot (fixed commands) — `scenarios/basic_recon.json`, `scenarios/persistence.json`
- **Tier 2:** LLM agent attacker — cross-family model (e.g. Gemini attacker vs. Llama honeypot)
- **Tier 4:** Prompt injection — `scenarios/prompt_injection.json`
- **Sessions:** 20/scenario/system for Tier 1+2, 10 for Tier 4
- **Systems under test:** Cowrie, llama3.2:3b, llama3.1:8b, cloud API variant

---

# Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools).

## Multi-Agent Chain

```
Claude (orchestrator) → Gemini CLI (executor) → Ollama/Gemma (local LLM)
```

## Key workflows
- `workflows/experiment_workflow.md` — how to run an experiment end-to-end
- Run `python analysis/compute_metrics.py results/*.jsonl` to get Pentad metrics

## Guardrails

### Always confirm before
- `git push`
- Deleting files outside `.tmp/` or `results/`
- Running attacker scripts against anything other than localhost

### Never do
- Point the attacker at external/production systems
- Commit `.env` or `results/` (contains interaction logs)
