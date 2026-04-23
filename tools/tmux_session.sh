#!/bin/bash
# Launches a named tmux session with the WAT layout.
# Run this at the start of every session instead of opening raw terminals.
#
# Usage:
#   ./tools/tmux_session.sh [session-name]
#   Default session name: pentest

SESSION="${1:-wat}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# If session already exists, just attach
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[*] Session '$SESSION' already exists — attaching."
    tmux attach -t "$SESSION"
    exit 0
fi

# --- Create session and main pane ---
tmux new-session -d -s "$SESSION" -n "main" -c "$PROJECT_ROOT"

# --- Split: right column (40% width) ---
tmux split-window -h -p 40 -t "$SESSION:main" -c "$PROJECT_ROOT"

# --- Split right column: top = subagents, bottom = log ---
tmux split-window -v -p 35 -t "$SESSION:main.2" -c "$PROJECT_ROOT"

# --- Label panes with a short banner ---
tmux send-keys -t "$SESSION:main.1" "echo '[ MAIN — work here ]'" Enter
tmux send-keys -t "$SESSION:main.2" "echo '[ SUBAGENTS — Gemini / Gemma output ]'" Enter
tmux send-keys -t "$SESSION:main.3" "echo '[ LOG ]' && touch .tmp/agent_bash_log.txt && tail -f .tmp/agent_bash_log.txt" Enter

# --- Source venv in main pane ---
tmux send-keys -t "$SESSION:main.1" "source .venv/bin/activate" Enter
tmux send-keys -t "$SESSION:main.1" "clear" Enter

# --- Focus main pane ---
tmux select-pane -t "$SESSION:main.1"

# --- Attach ---
tmux attach -t "$SESSION"
