# Workflow: Running the Honeypot Experiment

## Objective
Run controlled attack scenarios against Cowrie and LLM honeypot variants, collect session logs, and compute Evaluation Pentad metrics for Ch. 6.

## Prerequisites
- Docker Desktop running
- Ollama installed natively on Windows with target model pulled (`ollama pull llama3.1:8b`)
- `.env` file filled from `.env.example`

## Step 1 — Start the honeypot

```bash
# LLM variant (default model from .env)
docker compose up honeypot -d

# Verify it's listening
ssh root@localhost -p 2222   # any password — should get a shell
```

## Step 2 — Run a Tier-1 scenario

```bash
# 20 sessions of basic recon
docker compose run --rm -e SCENARIO=scenarios/basic_recon.json -e NUM_SESSIONS=20 attacker

# Results land in results/basic_recon_<timestamp>.jsonl
```

## Step 3 — Run all scenarios

```bash
for scenario in basic_recon persistence prompt_injection; do
  docker compose run --rm \
    -e SCENARIO=scenarios/${scenario}.json \
    -e NUM_SESSIONS=20 \
    attacker
done
```

## Step 4 — Compute metrics

```bash
python analysis/compute_metrics.py results/*.jsonl
```

## Step 5 — Repeat for each honeypot variant

Change `OLLAMA_MODEL` in `.env` to switch models:
- `llama3.2:3b` — small CPU baseline
- `llama3.1:8b` — main GPU variant
- For Cowrie: deploy Cowrie on port 2222 separately, point attacker at it

## Cleanup

```bash
docker compose down
ollama rm llama3.1:8b   # optional — removes model files from host
```

## Results structure

```
results/
  basic_recon_20260501_143022.jsonl       # full session logs (one JSON per line)
  basic_recon_20260501_143022_summary.csv # per-session summary for spreadsheet
```

## Metric mapping (Evaluation Pentad)

| Metric | Axis | Source |
|--------|------|--------|
| TNR (detected_as_honeypot=False rate) | Believability | attacker/run.py |
| avg_dwell_s, avg_cmds | Attacker Cost | attacker/run.py |
| cmd_success_rate | Fidelity | attacker/run.py |
| avg_latency_s | Defender Cost | attacker/run.py |
| cmd_diversity, unique_cmds | Data Capture | analysis/compute_metrics.py |
