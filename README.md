# Honeypot Experiment

Controlled evaluation of traditional vs. LLM-based SSH honeypots using the Evaluation Pentad framework.

Part of the DHBW Studienarbeit — "KI Honeypot". Writing lives in `../studienarbeit-honeypot`.

## Quick Start

```bash
# 1. Copy and fill env
cp .env.example .env

# 2. Pull the model (native on Windows — GPU access)
ollama pull llama3.1:8b

# 3. Start honeypot
docker compose up honeypot -d

# 4. Run a scenario (20 sessions)
docker compose run --rm -e SCENARIO=scenarios/basic_recon.json attacker

# 5. Compute metrics
python analysis/compute_metrics.py results/*.jsonl
```

## Structure

```
honeypot/       LLM SSH honeypot (asyncssh + Ollama backend)
attacker/       Experiment runner — connects via SSH, runs scenarios, logs results
scenarios/      Attack scenario definitions (Tier 1, 4)
analysis/       Metric computation from session logs
results/        Session logs — gitignored
docs/           findings.md — implementation notes from prototype phase
```

## Evaluation Pentad

| Axis | Metric | Measured by |
|------|--------|-------------|
| Believability | TNR | attacker/run.py |
| Fidelity | Command success rate | attacker/run.py |
| Attacker Cost | Dwell time, cmd count | attacker/run.py |
| Defender Cost | Response latency | attacker/run.py |
| Data Capture | Command diversity | analysis/compute_metrics.py |

See `workflows/experiment_workflow.md` for full instructions.
