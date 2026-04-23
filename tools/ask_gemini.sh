#!/bin/bash
# Subagent tool — sends a prompt to Gemini CLI in headless/yolo mode.
# Gemini can autonomously call shell tools, making it ideal for multi-step
# execution tasks you want to delegate without blocking Claude's context.
#
# Usage:
#   ./ask_gemini.sh "your prompt here"
#   cat output.txt | ./ask_gemini.sh "summarize this"
#
# Requirements:
#   - Gemini CLI installed: npm install -g @google/gemini-cli
#   - Authenticated: run `gemini` once interactively to cache credentials

QUESTION="$*"

if [ -z "$QUESTION" ]; then
    echo "Usage: $0 \"your prompt\""
    echo "       cat file.txt | $0 \"prompt about the file\""
    exit 1
fi

# Combine stdin + question if data is piped in
if [ ! -t 0 ]; then
    INPUT=$(cat)
    PROMPT="${QUESTION}

---
${INPUT}"
else
    PROMPT="$QUESTION"
fi

# -y = yolo mode: auto-approve all tool calls (Gemini acts autonomously)
# Output is logged to .tmp/gemini_log.txt and shown in terminal
GEMINI_LOG="$(dirname "$0")/../.tmp/gemini_log.txt"
mkdir -p "$(dirname "$GEMINI_LOG")"
echo "[$(date -Iseconds)] PROMPT: $QUESTION" >> "$GEMINI_LOG"
echo "---" >> "$GEMINI_LOG"
gemini -y -p "$PROMPT" 2>&1 | tee -a "$GEMINI_LOG"
echo "---" >> "$GEMINI_LOG"
