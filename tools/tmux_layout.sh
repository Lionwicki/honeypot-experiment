#!/bin/bash
# Opens two log panes side by side.
# Left: Claude bash log | Right: Gemini log
# Run inside an existing tmux session: bash tools/tmux_layout.sh

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$PROJECT/.tmp"
touch "$PROJECT/.tmp/agent_bash_log.txt"
touch "$PROJECT/.tmp/gemini_log.txt"

# Left pane → Claude bash log
tmux select-pane -t 0
tmux send-keys "echo '[ Claude commands ]' && tail -f $PROJECT/.tmp/agent_bash_log.txt" Enter

# Split right → Gemini log
tmux split-window -h
tmux send-keys "echo '[ Gemini output ]' && tail -f $PROJECT/.tmp/gemini_log.txt" Enter
