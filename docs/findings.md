# Implementation Findings

Running log of observed behaviour, bugs, and fixes during development.
Each entry has a date, the command that triggered it, what happened, and what was done about it.

---

## 2026-04-14 — Initial smoke test with gemma3:4b

### Setup
- Model: `gemma3:4b` (local Ollama, ~3.3GB, Google Gemma 3)
- Test: 4 commands run sequentially with state tracking
- Hardware: dev notebook (no GPU info recorded)

---

### Finding 1 — Cold-start timeout

**Command:** `whoami`
**What happened:** First request timed out at 30s. Second identical request succeeded in ~60s.
**Cause:** Ollama takes ~45-60s to load gemma3:4b into memory on first call. Subsequent calls are fast (~3-8s).
**Fix:** Bumped default timeout from 30s → 120s in `ollama_backend.py`.
**Thesis note:** Cold-start latency is irrelevant for a deployed honeypot (model stays warm). But per-command latency of 3-8s is still 60-160x slower than real bash — fingerprintable. See Ch. 7.1.

---

### Finding 2 — Chained commands cause timeout

**Command:** `cd /tmp && touch evil.sh`
**What happened:** Request timed out at 120s. No output, no state delta.
**Cause:** The `&&` operator caused the model to either over-think or enter a generation loop. Single commands work fine.
**Fix needed:** Split chained commands (`&&`, `;`, `|`) into individual LLM calls before sending. Implement in `ssh_handler.py` before the `query_ollama()` call.
**Status:** Open

---

### Finding 3 — Model hallucinates history commands

**Command:** `ls /etc` (second command in session)
**What happened:** Model output included commands that were never typed:
```
$ ls -l /root/.ssh
-rw------- 1 root root 889 Oct 26 14:35 authorized_keys
$ echo "attacker" >> /root/.ssh/authorized_keys
$ cat /var/log/auth.log
...
```
**Cause:** gemma3:4b is completing a plausible "attacker narrative" rather than just responding to the current command. It invented history entries mid-response.
**Fix needed:** Add an explicit rule to the system prompt: "Respond only to the single command on the last line. Do not invent or repeat prior commands."
**Status:** Open
**Thesis note:** This is a variant of the state drift problem — the model substitutes its own priors for the actual session state. Worth documenting in Ch. 6 (Limitations) as a quality difference between gemma3:4b and stronger models like llama3.1:8b.

---

### What worked correctly

| Command | Output | State delta parsed | Notes |
|---------|--------|--------------------|-------|
| `whoami` | `root` | yes | correct |
| `id` | `uid=0(root) gid=0(root) groups=0(root)` | yes | correct |
| `ls /etc` | listed files from our filesystem | yes | correct output, but see Finding 3 |
| `ls /tmp` | empty (correct) | yes | correct after `cd /tmp && touch evil.sh` timed out |

---

---

## 2026-04-14 — After fixes: command splitting + prompt rule 8

### Finding 4 — Fix 1 confirmed: chained commands now work

**Commands:** `cd /tmp && touch evil.sh` (split into two calls)
**What happened:** Both sub-commands completed successfully without timeout.
- `cd /tmp` → returned output, delta `{"cwd": "/tmp", ...}` applied correctly
- `touch evil.sh` → returned output, delta attempted
**Status:** Closed

---

### Finding 5 — Model wraps output in markdown code fences

**Command:** `cd /tmp`, `touch evil.sh`, `whoami`
**What happened:** gemma3:4b wraps responses in triple-backtick markdown blocks:
```
```bash
/ # cd /tmp
...
```
```
A real terminal never outputs markdown. An attacker would see the backticks.
**Cause:** gemma3:4b is trained heavily on markdown and defaults to it for code output.
**Fix needed:** Add to system prompt: "Never use markdown formatting, code fences, or backticks. Output raw terminal text only."
**Status:** Open

---

### Finding 6 — Model uses wrong prompt style (/ # instead of $ )

**Command:** `cd /tmp`
**What happened:** Model output used `/ # cd /tmp` — a BusyBox/Alpine-style prompt, not Ubuntu bash.
**Cause:** The model is generating its own prompt prefix inside the output, which is wrong — the SSH handler writes the prompt separately.
**Fix needed:** Add to system prompt: "Do not include a shell prompt (e.g. $ or #) at the start of your output. Output only what comes *after* the prompt."
**Status:** Open

---

### Finding 7 — State delta JSON wrapped in extra characters

**Raw delta received:**
```
{"cwd": "/tmp", "new_files": {"evil.sh": 0}, ...}\n```
{"cwd": "/tmp", "new_files": {"evil.sh": 10}, ...}'
```
Extra backtick or quote appended after closing brace — causes `json.JSONDecodeError`.
**Cause:** Markdown code fence bleed-over from Finding 5. The closing ``` lands after the JSON.
**Fix needed:** Strip trailing non-JSON characters in `response_parser.py` before `json.loads()`.
**Status:** Open (will be resolved by fixing Finding 5 at the prompt level, plus a defensive strip in the parser)

---

### Finding 8 — `ls /tmp` timed out (second call in sequence)

**Command:** `ls /tmp` (third LLM call in sequence, after cd + touch)
**What happened:** Request timed out at 120s.
**Cause:** Unknown — may be model load variance, or accumulated context length. Single commands work fine in isolation.
**Note:** Intermittent, not consistently reproducible. Monitor.
**Status:** Open (monitor)

---

---

## 2026-04-14 — Stop sequence + path fix verification run

### Finding 9 — Hallucinated follow-up commands: FIXED

**Commands tested:** `cd /tmp && touch evil.sh`, `ls /tmp`, `whoami`
**Before fix:** `whoami` returned `'root\n$$ bash'` — model emitted `$$` variant prompt line
**Fix applied:**
1. `ollama_backend.py`: expanded stop sequences to `["\n$ ", "\n# ", "\n$"]`
2. `ollama_backend.py` `_parse_response()`: added defensive regex strip: `re.sub(r'\n\$+\s.*$', '', clean_output, flags=re.DOTALL)`
**After fix:** `whoami` returns clean `'root'`. No hallucinated continuation.
**Status:** Closed

---

### Finding 10 — Relative path in state delta: FIXED

**What happened:** Model returned delta `{"new_files": {"evil.sh": 0}, ...}` (relative path).
`apply_state_delta` computed `parent = ""` (empty string), storing the file at `filesystem[""]` instead of `filesystem["/tmp"]`.
**Fix:** Added `_resolve_path()` to `SessionState` — joins relative paths with `self.cwd` before splitting into parent/name. All three delta sections (new_files, new_dirs, deleted) now resolve paths.
**After fix:** `evil.sh` correctly appears in `/tmp contents=['evil.sh']`.
**Status:** Closed

---

### Finding 11 — Root cause of timeouts: prompt ingestion latency (gemma3:4b too slow)

**What happened:** Both `cd /tmp` and `ls /tmp` time out at 120s on every run with the full prompt.
**Root cause confirmed by Gemini streaming test:** The hang is NOT long generation — it is **prompt ingestion**.
gemma3:4b on CPU hardware takes >106s to process a 500-char prompt and fails to produce any tokens
within 150s for the full 2.6k-char prompt. Generation never starts within our timeout window.
This is a fundamental capability limit of gemma3:4b on this hardware, not a bug in our code.

**Why simpler commands work:** `whoami` and `touch evil.sh` hit the model when it's already warm
(Ollama keeps the model loaded after first call). The short commands apparently complete ingestion
within 120s; longer prompts do not. Cold start + large prompt → guaranteed timeout.

**Prompt optimization applied:** `to_prompt_summary()` now uses a compact flat format instead of
indented JSON (~518 tokens vs ~653). This will benefit llama3.1:8b but does not fix gemma3:4b.

**Thesis value:** gemma3:4b failures map directly to Ch. 7 "Latency Fingerprinting":
  - An attacker running `ls /tmp` and waiting 120s immediately knows they are in a simulated shell.
  - Document as the "detectable baseline" — model efficiency (tokens/sec) is as critical as fidelity.
  - gemma3:4b = "fails believability on latency alone" — a clean data point for the evaluation tetrad.

**Fix:** Pull `llama3.1:8b` and re-run the same test sequence to validate the hypothesis.
**Status:** Closed as root cause identified. llama3.1:8b is the next test target.

---

---

## 2026-04-14 — llama3.2:3b smoke test

### Finding 12 — llama3.2:3b: no timeouts, correct state tracking, output format issues

**Model:** llama3.2:3b (Meta, 2.0 GB, Q4 quant). Pulled and tested immediately after.
**Hardware:** same i5-7300U, 7.6 GB RAM, no GPU.

**Results vs gemma3:4b:**

| Command | gemma3:4b | llama3.2:3b |
|---------|-----------|-------------|
| `cd /tmp` | TIMEOUT | `/tmp` (wrong output, correct delta) |
| `touch evil.sh` | TIMEOUT | echoed command (wrong output, correct delta) |
| `ls /tmp` | TIMEOUT | `evil.sh\n/tmp` (mostly correct, extra `/tmp`) |
| `whoami` | `root` | `root` (perfect) |

**State tracking: working.** Delta uses absolute path `/tmp/evil.sh` (no relative path bug),
cwd correctly updated, `evil.sh` appears in `/tmp contents`. A clear improvement over gemma3:4b.

**After fix iteration (rules 11 + comprehensive prompt stripping):**

| Command | Final output | Correct? |
|---------|-------------|----------|
| `cd /tmp` | `/tmp` | Partial (bash outputs nothing; fidelity issue for expert attackers) |
| `touch evil.sh` | `` (empty) | ✓ |
| `ls /tmp` | `total 0\ndrwxr-xr-x... evil.sh` | ✓ Realistic long-form listing |
| `whoami` | `root` | ✓ |

State tracking fully correct: `evil.sh` in `/tmp`, absolute paths in delta, cwd updated. No timeouts.

**Fixes applied:**
- Rule 11 in `prompt_builder.py`: explicit list of no-output commands
- Comprehensive `user@host:/path` stripping in `_parse_response` (multiline regex)
- Timeout raised 120s → 240s for context-accumulation overhead
- `DEFAULT_MODEL` switched to `llama3.2:3b`

**Remaining issue:** `cd /tmp` returns `/tmp` instead of empty — minor fidelity gap. An expert
  attacker would notice; automated scanners would not.

**Thesis note:** llama3.2:3b is viable on this hardware. No ingestion timeouts. Per-command
  latency ~3-30s depending on prompt size. Still fingerprintable by latency, but functionally
  correct for demonstrating the prototype.

---

---

## 2026-04-14 — First live interactive SSH test (llama3.2:3b)

### Finding 13 — Interactive session: connection + prompt work, output quality issues

**Test:** Live SSH connection via `ssh root@localhost -p 2222`, manual command input.

**What worked:**
- SSH handshake, RSA key fingerprint, password prompt — all correct
- Prompt format `root@webserver-prod:~#` — convincing
- `whoami` returns `root` (with artifact, see below)

**Issues observed:**

**A) Unknown command returns wrong error**
`hello` → `Hello World!` instead of `bash: hello: command not found`
Model interpreted "hello" as a greeting, not a shell command.
Rule 2 ("simulate bash behaviour faithfully") not followed for unrecognised commands.

**B) History contamination**
`id` (typed after `hello`) returned `Hello World!` before the real output.
The bad output from `hello` was stored in history and the model copied the pattern.
This is the cascade error problem — one bad response pollutes all subsequent prompts.

**C) `root@webserver-prod` leaking through stripping**
`whoami` output: `root@webserver-prod\nroot` — the `root@webserver-prod` (no path suffix) 
slips past the defensive regex `user@host:/path` because it has no colon+path.
Fix: extend regex to also strip `user@host` without path.

**D) Command echoed in output**
Output shows `whoami\nroot` — the command name appears before the result.
The SSH handler echoes typed characters (correct), but the model also outputs the command name.
Add to prompt: "Do not repeat the command name in your output."

**Status of issues:** Open — see items 11-14 in Open Issues table.

---

## Open Issues

| # | Issue | Severity | Status | Fix |
|---|-------|----------|--------|-----|
| 1 | Chained commands time out | High | **Closed** | Split in `ssh_handler.py` |
| 2 | Model hallucinates history commands | Medium | **Closed** | Rule 8 added to prompt |
| 3 | Output wrapped in markdown code fences | High | **Closed** | Rules 9+10 added to prompt |
| 4 | Model outputs wrong prompt style (/ # ) | Medium | **Closed** | Rules 9+10 added to prompt |
| 5 | State delta JSON has trailing junk chars | Medium | **Closed** | Defensive `rfind('}')` strip in parser |
| 6 | Intermittent timeout on sequential calls | Low | **Closed** | Not intermittent — prompt ingestion bottleneck (see Finding 11) |
| 7 | Model still hallucinates follow-up commands after `ls` | High | **Closed** | Stop sequences + defensive regex strip in `_parse_response` |
| 8 | `cd /tmp` returns "No such file or directory" despite /tmp in filesystem | Medium | **Closed** | Masked by timeout — root cause is prompt ingestion (Finding 11), not logic error |
| 9 | Relative path in state delta (`evil.sh` not `/tmp/evil.sh`) | Medium | **Closed** | `_resolve_path()` added to `SessionState` |
| 10 | `cd` returns `/tmp` instead of empty | Low | Open | Minor fidelity issue; llama3.2:3b interprets `cd` as pwd-printing |
| 11 | Unknown commands return wrong error (e.g. `hello` → `Hello World!`) | High | Open | Add rule: "unrecognised commands must return `bash: <cmd>: command not found`" |
| 12 | Bad output poisons history (cascade contamination) | High | Open | Strip/sanitise output before recording in history; or cap max_history lower |
| 13 | `root@webserver-prod` without path not stripped | Medium | Open | Extend regex to catch `user@host` without colon+path suffix |
| 14 | Model echoes command name in output | Medium | Open | Add rule: "Do not repeat the command name at the start of your output" |
| 15 | No session termination for automated attacker loops | High | **Closed** | `MAX_TURNS=25` watchdog added to `ssh_handler.py` — closes with "Connection closed by remote host." |
