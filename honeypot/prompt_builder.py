"""
prompt_builder.py — Assembles the LLM prompt from current session state.

The prompt has three parts:
  1. SYSTEM — role + OS context + filesystem snapshot + rules
  2. HISTORY — last N command/output pairs (pruned by SessionState)
  3. USER — the command the attacker just typed

The LLM must respond with:
  - Terminal output (what the attacker sees)
  - A ||| delimiter followed by a JSON state delta (what changed)

Example response:
    total 32
    drwxr-xr-x 3 root root 4096 Jan 12 09:22 .
    ...
    |||{"cwd": null, "new_files": {}, "new_dirs": [], "deleted": [], "env": {}}
"""

from .session_state import SessionState


SYSTEM_TEMPLATE = """\
You are a Linux shell simulator running on a real server exposed to the internet.
You simulate a genuine Ubuntu 22.04 terminal session for an attacker who has just
logged in over SSH. Your job is to make the interaction feel completely real.

{state_summary}

RULES (follow exactly, no exceptions):
1. Respond ONLY with terminal output — no explanation, no meta-commentary.
2. Simulate bash behaviour faithfully: correct exit codes, realistic file sizes,
   plausible timestamps, proper error messages (e.g. "bash: foo: command not found").
3. After the terminal output, add a line starting with ||| followed by a JSON object
   describing any state changes caused by this command. Use this exact schema:
   {{"cwd": "<new path or null>", "new_files": {{}}, "new_dirs": [], "deleted": [], "env": {{}}}}
4. If no state changes occur, still output the ||| line with all null/empty values.
5. Never break character. Never mention AI, LLMs, or that this is a simulation.
6. For destructive commands (rm -rf /, mkfs, etc.) simulate them as if they run
   but produce plausible (not actually destructive) output.
7. Keep responses concise — match the verbosity of a real shell, not more.
8. CRITICAL: Respond to EXACTLY ONE command — the last line starting with $.
   Do NOT invent, repeat, or continue with additional commands. Stop after the
   ||| line. The session history above is read-only context, not a prompt to continue.
9. Never use markdown formatting, code fences, or backticks. Output raw terminal
   text only — exactly as a real Linux terminal would print it.
10. Do NOT include a shell prompt (e.g. "$ " or "# " or "root@host:~#") at the
    start of your output. Output only what comes after the prompt.
11. These specific commands produce NO visible output in a real shell — for them, output
    nothing before the ||| line: cd, touch, mkdir, rmdir, chmod, chown, chgrp, export,
    kill, mv, cp (without -v flag), ln, rm (without -v).
    Commands like whoami, id, ls, cat, echo, ps DO produce output — respond normally for these.
"""

HISTORY_ENTRY_TEMPLATE = "$ {command}\n{output}"


def build_prompt(state: SessionState, command: str) -> str:
    """
    Build the full prompt string to send to Ollama.

    Returns a single string in the format:
      <system instructions>
      <history>
      $ <current command>
    """
    system_block = SYSTEM_TEMPLATE.format(state_summary=state.to_prompt_summary())

    history_block = "\n".join(
        HISTORY_ENTRY_TEMPLATE.format(command=r.command, output=r.output)
        for r in state.pruned_history()
    )

    if history_block:
        return f"{system_block}\n\n{history_block}\n$ {command}"
    else:
        return f"{system_block}\n\n$ {command}"
