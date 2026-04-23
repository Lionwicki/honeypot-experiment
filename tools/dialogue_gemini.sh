#!/bin/bash
# dialogue_gemini.sh — Start or continue a reasoning dialogue with Gemini.
#
# Usage:
#   First turn:    ./tools/dialogue_gemini.sh start
#   Follow-up:     ./tools/dialogue_gemini.sh continue
#   End session:   ./tools/dialogue_gemini.sh end
#
# Before calling:
#   - Write the task to agents/shared/task.md
#   - Write Claude's position to agents/claude/sparring.md
#
# After calling:
#   - Gemini's reasoning is printed to stdout (captured by caller)
#   - Claude writes response.md and appends to dialogue.md from the output
#
# Design note: This script does NOT use -y (YOLO mode). Dialogue is pure
# reasoning — Gemini needs no tool access. All context is passed as prompt text.
# YOLO mode is reserved for ask_gemini.sh (execution tasks only).

MODE="${1:-start}"
BRIEFING="agents/gemini/briefing.md"
TASK="agents/shared/task.md"
SPARRING="agents/claude/sparring.md"
DIALOGUE="agents/shared/dialogue.md"

if [ ! -f "$BRIEFING" ]; then
    echo "ERROR: $BRIEFING not found. Run from project root."
    exit 1
fi

case "$MODE" in
  start)
    echo "Starting new Gemini dialogue session..."
    PROMPT="$(cat $BRIEFING)

---

## Current Task

$(cat $TASK)

---

## Claude's Position

$(cat $SPARRING)

---

## Your job

Reason about the task and Claude's position. Output your response in the format
defined in your briefing (Position / Reasoning / Where I agree / Where I'd push back /
Open questions). Do not call any tools, do not modify any files. Just reason and write."

    gemini -p "$PROMPT" 2>&1
    ;;

  continue)
    echo "Resuming Gemini dialogue session..."
    PROMPT="## Follow-up from Claude

$(cat $SPARRING)

Read the context above (your previous reasoning is in your session memory).
Respond with a revised or extended position using the same format as before.
Do not call any tools, do not modify any files."

    gemini --resume latest -p "$PROMPT" 2>&1
    ;;

  end)
    echo "Closing dialogue session..."
    PROMPT="This dialogue is complete. Output a final 3-5 bullet summary of
what was decided or concluded. Do not call any tools, do not modify any files."

    gemini --resume latest -p "$PROMPT" 2>&1
    echo "---"
    echo "Dialogue closed. Paste the summary above into $DIALOGUE under 'Final Summary'."
    ;;

  *)
    echo "Usage: $0 [start|continue|end]"
    exit 1
    ;;
esac
