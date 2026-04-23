#!/bin/bash
# Subagent tool — sends a prompt to local Gemma 3 4B via Ollama REST API.
# Uses the API instead of `ollama run` to avoid ANSI escape codes in output.
#
# Usage:
#   ./ask_gemma.sh "your prompt here"
#   cat scan_output.txt | ./ask_gemma.sh "summarize the open ports and services"

MODEL="gemma3:4b"
OLLAMA_URL="http://localhost:11434/api/generate"

QUESTION="$*"

if [ -z "$QUESTION" ]; then
    echo "Usage: $0 \"your prompt\""
    echo "       cat file.txt | $0 \"prompt about the file\""
    exit 1
fi

# Combine stdin + question into a single prompt if data is piped in
if [ ! -t 0 ]; then
    INPUT=$(cat)
    PROMPT="${QUESTION}

---
${INPUT}"
else
    PROMPT="$QUESTION"
fi

# Escape prompt for JSON
ESCAPED=$(printf '%s' "$PROMPT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")

curl -s --max-time 120 "$OLLAMA_URL" \
  -d "{\"model\":\"$MODEL\",\"prompt\":$ESCAPED,\"stream\":false}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['response'])"
