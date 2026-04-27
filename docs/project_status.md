# Projektstand Honeypot-Experiment

Stand: 2026-04-27

---

## Abgeschlossen

### Tier-1: Scripted Bot
- Szenarien: basic_recon, persistence, prompt_injection — je 10 Sessions gegen llama3.1:8b
- Ergebnisse: `results/basic_recon_20260427_151133.jsonl`, `results/persistence_20260427_153349.jsonl`, `results/prompt_injection_20260427_15*.jsonl`
- Findings 14–19 in `docs/findings.md`

### Tier-2: LLM Attacker (gemma4:e4b vs. llama3.1:8b)
- 20 Sessions, Ergebnis: `results/llm_attacker_gemma4_e4b_20260427_201317.jsonl`
- **TNR = 10% (roh), 25% (latenzkorrigiert)**
- Avg. Commands: 19.0 | Avg. Dwell: 102.9s | Avg. Detection Turn: 10.1
- Findings 20–28 in `docs/findings.md`

---

## Offen / Nächste Schritte

| # | Aufgabe | Priorität |
|---|---------|-----------|
| 1 | Cowrie Baseline aufsetzen + Tier-1 Szenarien laufen lassen | Hoch |
| 2 | llama3.2:3b als Honeypot testen (Tier-1 + Tier-2) | Hoch |
| 3 | Cloud API Variant (4. System laut CLAUDE.md) | Mittel |
| 4 | Tier-4 Prompt Injection gegen llama3.2:3b | Mittel |
| 5 | `analysis/compute_metrics.py` für vollständige Evaluation Pentad | Hoch |
| 6 | Vergleichstabelle: Cowrie vs. llama3.2:3b vs. llama3.1:8b | Hoch |

---

## Technischer Stand

### Deployment
- Honeypot: Docker Container, Port 2222
- Ollama: nativ auf Windows Host, Port 11434
- `docker-compose.yml`: `OLLAMA_HOST=host.docker.internal` (kein `http://` Prefix)

### Modelle (Ollama)
| Modell | Rolle | Status |
|--------|-------|--------|
| llama3.1:8b | Honeypot primär | Getestet |
| gemma4:e4b | Attacker Tier-2 | Getestet |
| llama3.2:3b | Honeypot sekundär | Noch nicht getestet |

### Schlüsselfiles
| File | Inhalt |
|------|--------|
| `honeypot/ollama_backend.py` | Ollama-Integration, `_strip_command_echo()` |
| `honeypot/ssh_handler.py` | asyncssh, `session_started()` schreibt initialen Prompt |
| `attacker/llm_attacker.py` | Tier-2 Attacker, `/api/chat`, `detect_indicators()` mit 8 Heuristiken |
| `attacker/run.py` | Tier-1 Scripted Bot |
| `docs/findings.md` | 28 Findings dokumentiert |
| `results/` | gitignored, alle JSONL Logs |

### Implementierte Heuristiken in `detect_indicators()`
`safety_refusal`, `markdown_fence`, `high_latency`, `self_disclosure`, `content_substitution`, `bash_history_mutation`, `root_needs_sudo`, `session_replay`, `json_context_leak`, `llm_explanation`
