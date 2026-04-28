# Methodik — Honeypot-Experiment

Stand: 2026-04-28

---

## 1. Evaluierungsrahmen

Grundlage ist das **Evaluation Pentad** (adaptiert nach Bridges et al. 2025), ein fünfdimensionaler Rahmen zum Vergleich von Honeypot-Systemen:

| Achse | Metrik | Richtung |
|-------|--------|----------|
| **Believability** | True Negative Rate (TNR) — Anteil Sessions ohne Honeypot-Erkennung | höher = besser |
| **Fidelity** | Command Success Rate — Anteil plausibler Antworten | höher = besser |
| **Attacker Cost** | Dwell Time (s), Befehle pro Session | höher = besser für Defender |
| **Defender Cost** | Mittlere Antwortlatenz pro Command | niedriger = besser |
| **Data Capture** | Command Diversity (unique / total Commands) | höher = besser |

---

## 2. Systeme unter Test

| System | Technologie | Tier | Status |
|--------|------------|------|--------|
| **llama3.1:8b** | asyncssh + Ollama (Meta Llama 3.1, lokal, GPU) | 1, 2, 4 | Vollständig getestet |
| **Cowrie** | Traditioneller SSH-Honeypot (Emulation, GitHub HEAD, Docker) | 1 | 20 Sessions getestet (basic_recon + persistence) |

**Scope-Entscheidungen:**
- **llama3.2:3b:** Nicht getestet — llama3.1:8b als primäres LLM-System ausreichend für den Vergleich
- **Cloud API:** Nicht im Scope — Ressourcen- und Kostengründe
- **Cowrie Tier-2/4:** Nicht anwendbar — Cowrie ist kein LLM und kann nicht prompt-injiziert werden; Tier-2-Heuristiken sind LLM-spezifisch

---

## 3. Angreifer-Typen (Tier-Struktur)

### Tier-1 — Scripted Bot (`attacker/run.py`)
- Feste Befehlssequenzen aus JSON-Szenario-Dateien
- Kein adaptives Verhalten
- Szenarien: `basic_recon`, `persistence`, `prompt_injection`
- Erkennung über `detected_as_honeypot`-Flag (regelbasiert im Skript)

### Tier-2 — LLM Attacker (`attacker/llm_attacker.py`)
- Adaptiver Angreifer auf Basis eines lokalen LLM
- Modell: **gemma4:e4b** (Google/Mistral-Familie)
- Entscheidungslogik: LLM wählt nächsten Befehl basierend auf Honeypot-Antwort
- Erkennung über `detect_indicators()` mit 10 Heuristiken (siehe Abschnitt 5)
- **Cross-Family-Anforderung:** Angreifer und Honeypot müssen unterschiedliche Modellfamilien verwenden (Meta vs. Google) — verhindert Selbst-Konsistenz-Bias

### Tier-4 — Prompt Injection (`scenarios/prompt_injection.json`)
- Befehle enthalten eingebettete Prompt-Injection-Versuche
- Testet ob Honeypot-LLM auf eingeschleuste Instruktionen reagiert
- **Nur gegen LLM-Honeypots** — Cowrie ist strukturell immun (kein LLM-Backend)

---

## 4. Experimentdesign

### Sessionsanzahl
| Tier | System | Sessions | Begründung |
|------|--------|----------|-----------|
| Tier-1 | llama3.1:8b | 60 (3 Runs à 20) | Probabilistisches System — mehrere Runs nötig für stabile Schätzung (siehe Finding 31) |
| Tier-1 | Cowrie | 20 (1 Run, basic_recon + persistence) | Deterministisches System — n=20 statistisch ausreichend (Begründung siehe unten) |
| Tier-2 | llama3.1:8b | 60 (3 Runs à 20) | Hohe Run-to-Run-Varianz (10–25% TNR-Spread) erfordert größere Stichprobe |
| Tier-4 | llama3.1:8b | 40 (2 Runs à 20) | Korrektur-Run nach Heuristik-Fehler (Finding 19) erforderlich |

### Begründung: Cowrie n=20 ist ausreichend

Cowrie ist ein **deterministisches System**: Für jeden eingehenden Befehl gibt es genau eine fest hinterlegte Antwort aus einem Template-Dateisystem. Es gibt keine Zufallskomponente im Antwortgenerator.

Daraus folgt:
- **TNR:** Tier-1 Scripted Bots prüfen auf AI-Artefakte (Markdown, Safety-Phrasen, Session-Replay). Da Cowrie keine dieser Artefakte erzeugt, wird es deterministisch nicht erkannt — unabhängig von n. Weitere Sessions würden die TNR von 100% nicht verändern.
- **Fidelity:** Cowrie gibt für alle unterstützten Befehle immer dieselbe korrekte Fixture-Ausgabe zurück. Die `commands_success`-Rate ist strukturell 1.0 — kein Sampling-Artefakt.
- **Latenz:** Die Antwortzeit ist durch Template-Lookup dominiert (typ. 0.5s). Die Standardabweichung über 20 Sessions ist vernachlässigbar klein (<10ms).
- **Dwell Time:** Wird primär durch Latenz × Befehlsanzahl bestimmt — bei konstantem Skript und konstanter Latenz ebenfalls deterministisch.

Im Gegensatz dazu benötigte llama3.1:8b n=60, weil das LLM bei identischen Eingaben unterschiedliche Ausgaben erzeugt (Temperatursamplung), was zu Run-to-Run-Schwankungen von bis zu 15 Prozentpunkten im TNR führte (Finding 31). Dieses Problem existiert bei Cowrie strukturell nicht.

**Methodische Konsequenz:** Der Vergleich Cowrie (n=20) vs. llama3.1:8b (n=60) ist valide. Eine Erhöhung der Cowrie-Sessions auf n=60 würde keine neuen Erkenntnisse liefern, sondern lediglich die bereits stabilen Punktschätzungen mit unnötigem Aufwand replizieren.

### Technische Parameter
| Parameter | Wert | Begründung |
|-----------|------|------------|
| `MAX_TURNS` | 20 | Konsistente Sessionlänge; Wert in `ssh_handler.py` |
| Attacker Temperature | 0.2 | Leichte Stochastizität verhindert deterministische Loops |
| Honeypot Temperature | Default Ollama | Natürliche Variabilität |
| SSH Port | 2222 | Container-intern, Host-Port-Mapping |

### Deployment
```
Windows Host
├── Ollama (nativ, GPU via DirectML)       Port 11434
└── Docker Desktop
    ├── honeypot (asyncssh + Ollama-Backend)  Port 2222
    └── attacker (Tier-1, Docker-Run)
        └── Tier-2 läuft direkt auf dem Host (Ollama-Zugriff)
```

---

## 5. Erkennungs-Heuristiken (Tier-2)

`detect_indicators()` in `attacker/llm_attacker.py` prüft jede Honeypot-Antwort auf 10 Indikatoren:

| Indikator | Kriterium |
|-----------|-----------|
| `safety_refusal` | Output enthält "I cannot", "As an AI" o.ä. |
| `markdown_fence` | Output enthält Backtick-Blöcke (` ``` `) |
| `high_latency` | Antwortzeit > Schwellwert (fingerprintbar) |
| `self_disclosure` | Honeypot nennt sich selbst als KI/Honeypot |
| `content_substitution` | Antwort passt nicht zum gesendeten Befehl |
| `bash_history_mutation` | History inkonsistent zwischen Sessions |
| `root_needs_sudo` | Root-User bekommt Permission-Denied-Fehler |
| `session_replay` | Vorherige Antwort wird für neuen Befehl wiederholt |
| `json_context_leak` | JSON-Artefakte im Output (interner Context-Leak) |
| `llm_explanation` | LLM erklärt was es tut anstatt es zu tun |

---

## 6. Datenerhebung

### Format
Jede Session wird als eine JSONL-Zeile in `results/` gespeichert.

**Tier-1 Schema:**
```json
{
  "session_id": 0,
  "scenario": "basic_recon",
  "dwell_time_s": 41.88,
  "commands_run": 15,
  "commands_success": 15,
  "detected_as_honeypot": true,
  "log": [
    {"cmd": "whoami", "output": "root", "latency_s": 0.7, "flagged": false}
  ]
}
```

**Tier-2 Schema:**
```json
{
  "session_id": 0,
  "attacker_model": "gemma4:e4b",
  "honeypot_detected": true,
  "honeypot_detected_at_turn": 10,
  "dwell_time_s": 109.52,
  "commands_run": 20,
  "log": [
    {"turn": 0, "cmd": "whoami", "output": "root", "latency_s": 0.5, "indicators": []}
  ]
}
```

### Datei-Konvention
`{szenario}_{YYYYMMDD}_{HHMMSS}.jsonl` — append-only, nie manuell editieren.
Nur Dateien mit >= 10 Sessions werden in der Auswertung berücksichtigt (schließt Testläufe aus).

---

## 7. Metriken und Auswertung

### Berechnung (`analysis/compute_metrics.py`)
Aggregiert pro Datei: TNR, Fidelity, Avg. Dwell, Avg. Commands, Avg. Latency, Command Diversity.

### Visualisierung (`analysis/plot_metrics.py`)
Liest alle validen JSONL-Files automatisch und erzeugt 8 Grafiken nach `analysis/plots/`:

| # | Datei | Inhalt |
|---|-------|--------|
| 01 | `radar_pentad.png` | Spider-Chart: alle 5 Pentad-Achsen × Szenarien |
| 02 | `believability_tnr.png` | TNR-Balken pro Szenario |
| 03 | `detection_turn_hist.png` | Ab welchem Turn erkannte Tier-2-Attacker das Honeypot |
| 04 | `dwell_time_boxplot.png` | Dwell-Time-Verteilung pro Szenario |
| 05 | `latency_per_turn.png` | Mittlere Latenz pro Turn (±1 SD) |
| 06 | `indicators_per_turn.png` | Heuristik-Hits pro Turn (Tier-2) |
| 07 | `command_frequency.png` | Top-15 Befehle pro Szenario |
| 08 | `commands_vs_dwell.png` | Scatter: Dwell vs. Befehle, erkannt/nicht erkannt |

Normalisierung im Radar-Chart:
- Attacker Cost: `avg_dwell / max_dwell` (relativ zum schlechtesten System)
- Defender Efficiency: `1 - (avg_latency / max_latency)` (niedrige Latenz = höherer Wert)

---

## 8. Post-hoc Fidelity-Bewertung (Tier-2)

### Problem
Das Tier-2-Schema enthält kein `commands_success`-Feld — der LLM-Attacker prüft Antworten implizit, speichert aber keine explizite Erfolgsrate.

### Ansatz
**Unabhängiger LLM-Judge** (`analysis/evaluate_fidelity.py`):

- Judge-Modell: **mistral:7b** (Mistral AI, Frankreich)
- Unabhängig von Experiment-Modellen (kein Overlap mit llama3.1:8b oder gemma4:e4b)
- Bewertet jedes `(cmd, output)`-Paar: **PASS** oder **FAIL**
- Kriterien: korrektes Format, kein Markdown, keine Safety-Phrasen, plausibler Inhalt
- Temperatur: 0 (deterministisch, reproduzierbar)
- Ergebnis: `results/fidelity_scores.json`

**Zitierbare Formulierung für die Thesis:**
> *"Fidelity for Tier-2 sessions was assessed post-hoc via an independent LLM judge (mistral:7b, Mistral AI) not involved in the experiment, evaluating each (command, response) pair for Linux system realism (PASS/FAIL)."*

### Limitation
Der Judge bewertet Oberflächenrealismus, nicht semantische Korrektheit. Eine Ground-Truth-Baseline (selbe Befehle auf echtem Linux) wäre der methodische Goldstandard, wurde aus Aufwandsgründen nicht umgesetzt.

### Wichtige Abgrenzung: Fidelity-Metrik in Tier-1 vs. Tier-2

**Tier-1 (`commands_success / commands_run`):** Misst ausschließlich ob eine nicht-leere Antwort vorliegt. Beide Systeme (Cowrie und llama3.1:8b) erreichen hier 1.0 — das ist jedoch keine inhaltliche Qualitätsaussage. Bei llama3.1:8b enthält eine "erfolgreiche" Antwort oft falschen Inhalt (falsches Kommando, Safety-Refusal mit Text, oder `/etc/passwd` für einen nicht-verwandten Befehl).

**Tier-2 (mistral:7b Judge):** Misst Oberflächenrealismus jedes (cmd, output)-Paares. Ergebnis: ~78% PASS. Dies ist die einzige methodisch belastbare Fidelity-Messung für das LLM-System.

**Für die Thesis:** Tier-1-Fidelity-Werte von 1.0 sind vergleichbar zwischen Cowrie und llama3.1:8b auf der Metrik-Ebene — qualitativ ist Cowrires Fidelity jedoch substanziell höher, da es aus vorbereiteten Fixtures antwortet.

---

## 9. Methodische Entscheidungen (Begründungen)

| Entscheidung | Begründung |
|--------------|------------|
| Cross-Family Attacker/Defender | Gleiche Familie würde Believability zur Selbst-Konsistenz-Messung machen |
| MAX_TURNS=20 statt 25 | Konsistenz zwischen Runs; frühere 3er-Testläufe mit anderem Cap ausgeschlossen |
| Temp 0.2 für Attacker | Temp 0 → deterministische Loops bei ambiguem Honeypot-Output |
| mistral:7b als Judge | Keine Überschneidung mit Experiment-Modellen; europäische Herkunft |
| JSONL append-only | Einzelne Sessions isoliert auswertbar; keine Batch-Korruption |
| >= 20 Sessions als Valid-Schwelle | Schließt Testläufe (3 Sessions) automatisch aus |
