# Projektstand Honeypot-Experiment

Stand: 2026-04-28

---

## Abgeschlossen

### Tier-1: Scripted Bot (llama3.1:8b) — n=60 je Szenario
- basic_recon: 60 Sessions (3 Runs) | TNR=96.7% | Dwell=33.4s | Lat=2.19s
- persistence: 60 Sessions (3 Runs) | TNR=88.3% | Dwell=15.1s | Lat=1.14s
- prompt_injection: 40 Sessions (2 Runs) | TNR=47.5% | Dwell=13.9s | Lat=1.03s
- Findings 14–19, 29–30 in `docs/findings.md`

### Tier-2: LLM Attacker (gemma4:e4b vs. llama3.1:8b) — n=60
- 3 vollstaendige Runs a 20 Sessions | TNR=18.3% | Avg Dwell=100.7s | Avg Det. Turn=9.2
- Files: `llm_attacker_gemma4_e4b_20260427_201317.jsonl`, `_142132.jsonl`, `_151810.jsonl`
- Findings 20–28, 31–34 in `docs/findings.md`

### Cowrie Tier-1 — n=20 je Szenario
- basic_recon: 20 Sessions | TNR=100% | Dwell=8.2s | Lat=0.507s
- persistence: 20 Sessions | TNR=100% | Dwell=7.1s | Lat=0.500s
- Files: `basic_recon_cowrie_20260428_145152.jsonl`, `persistence_cowrie_20260428_145512.jsonl`
- Findings 35–36 in `docs/findings.md`

### Fidelity-Judge (mistral:7b)
- Alle 3 llm_attacker-Files evaluiert | Combined Fidelity ~0.78 (912/1169 PASS)
- Ergebnis: `results/fidelity_scores.json`
- Finding 37 in `docs/findings.md`

### Analyse-Infrastruktur
- `analysis/compute_metrics.py` — Evaluation Pentad Metriken (Text)
- `analysis/plot_metrics.py` — 9 Grafiken nach `analysis/plots/` (inkl. Cowrie-Vergleichs-Radar)
- `analysis/evaluate_fidelity.py` — Post-hoc Fidelity-Judge via mistral:7b (ausgefuehrt)
- `docs/methodology.md` — vollstaendige Methodikdokumentation inkl. Fidelity-Abgrenzung
- `docs/findings.md` — 38 Findings

### Modelle (Ollama, lokal verfuegbar)
| Modell | Rolle | Status |
|--------|-------|--------|
| llama3.1:8b | Honeypot primaer | Vollstaendig getestet |
| gemma4:e4b | Attacker Tier-2 | Vollstaendig getestet |
| mistral:7b | Fidelity-Judge | Ausgefuehrt (fidelity_scores.json) |
| llama3.2:3b | — | Nicht im Scope |

---

## Ergebnisse — Systemvergleich

| Metrik | Cowrie T1 (n=20) | llama T1 (n=60) | llama T2 (n=60) | llama T4 (n=40) |
|--------|-----------------|-----------------|-----------------|-----------------|
| TNR | **100%** | 92.5%* | 18.3% | 47.5% |
| Fidelity (surface) | 1.000 | 1.000 | 0.78 (Judge) | 1.000 |
| Avg Dwell | 7.6s | 24.2s | **100.7s** | 13.9s |
| Avg Latenz | **0.50s** | 1.67s | 2.74s | 1.03s |

\* Ø ueber basic_recon (96.7%) + persistence (88.3%)

---

## Offen / Naechste Schritte

| # | Aufgabe | Status |
|---|---------|--------|
| 1 | Studienarbeit schreiben (Ergebniskapitel) | Naechster Schritt |
| 2 | Grafiken aus `analysis/plots/` in Thesis einbinden | Bereit |
| 3 | Findings 35-38 als Grundlage fuer Vergleichskapitel | Bereit |

**Nicht mehr im Scope:** llama3.2:3b, Cloud API Variant, weitere Cowrie-Runs

---

## Technischer Stand

### Deployment
- LLM-Honeypot: Docker Container, Port 2222, `OLLAMA_HOST=host.docker.internal`
- Cowrie: Docker Container, Port 2223, Dockerfile.cowrie (GitHub HEAD)
- Ollama: nativ auf Windows Host, Port 11434
- Tier-2 Attacker: direkt auf Host (nicht Docker), Ollama-Zugriff via localhost

### Run-Commands

**Tier-1 llama (Docker):**
```bash
docker-compose up honeypot -d
docker-compose run --rm -e SCENARIO=basic_recon -e NUM_SESSIONS=20 attacker
docker-compose run --rm -e SCENARIO=persistence -e NUM_SESSIONS=20 attacker
docker-compose run --rm -e SCENARIO=prompt_injection -e NUM_SESSIONS=20 attacker
```

**Tier-1 Cowrie (Docker):**
```bash
docker-compose --profile cowrie up cowrie -d
docker-compose --profile cowrie run --rm -e SCENARIO=basic_recon -e NUM_SESSIONS=20 attacker-cowrie
docker-compose --profile cowrie run --rm -e SCENARIO=persistence -e NUM_SESSIONS=20 attacker-cowrie
```

**Tier-2 (Host):**
```bash
python attacker/llm_attacker.py --sessions 20 --max-turns 20
```

**Analyse:**
```bash
python analysis/evaluate_fidelity.py   # Fidelity-Judge (mistral:7b)
python analysis/plot_metrics.py        # 9 Grafiken neu generieren
```

### Schluesselfiles
| File | Inhalt |
|------|--------|
| `honeypot/ollama_backend.py` | Ollama-Integration, `_strip_command_echo()` |
| `honeypot/ssh_handler.py` | asyncssh, MAX_TURNS Watchdog |
| `attacker/llm_attacker.py` | Tier-2 Attacker, `detect_indicators()` (10 Heuristiken) |
| `attacker/run.py` | Tier-1 Scripted Bot |
| `analysis/compute_metrics.py` | Evaluation Pentad Metriken |
| `analysis/plot_metrics.py` | 9 Grafiken, automatisches File-Discovery, Cowrie-Radar |
| `analysis/evaluate_fidelity.py` | Post-hoc Fidelity via mistral:7b |
| `docs/methodology.md` | Vollstaendige Methodikdokumentation |
| `docs/findings.md` | 38 Findings |
| `results/` | gitignored, alle JSONL Logs |
| `results/fidelity_scores.json` | Judge-Ergebnis (mistral:7b, ausgefuehrt) |
