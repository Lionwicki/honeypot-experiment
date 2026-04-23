"""
PreToolUse guardrail hook for Claude Code.
Blocks dangerous Bash commands that require explicit user confirmation.
Runs before every Bash tool call. Exit 2 = block the command.

Customize the BLOCKED list for your project's risk profile.
"""

import sys
import json
import re

data = json.load(sys.stdin)
cmd = data.get('tool_input', {}).get('command', '')

# --- Commands that always require explicit user confirmation ---
# Customize this list per project. These are sensible universal defaults.
BLOCKED = [
    # Git: destructive / publishing
    'git push',
    'git reset --hard',
    'git rebase',
    'git clean',
    'git branch -D',

    # System changes
    'apt install',
    'apt-get install',
    'curl | bash',
    'wget | bash',
    'pip install --system',

    # Database destruction
    'DROP TABLE',
    'TRUNCATE TABLE',

    # Project-specific: add patterns below
    # 'your-sensitive-command',
]

for pattern in BLOCKED:
    if pattern in cmd:
        msg = (
            f'\033[0;31m'
            f'GUARDRAIL BLOCKED: "{pattern}" requires explicit user confirmation. '
            f'Tell Claude to proceed only after you approve.'
            f'\033[0m'
        )
        print(msg, file=sys.stderr)
        sys.exit(2)

# --- rm -r/-rf: block unless targeting .tmp/ ---
if re.search(r'rm\s+(-\w*[rR]\w*|--(recursive|force))', cmd):
    if '.tmp/' not in cmd and '.tmp ' not in cmd:
        msg = (
            '\033[0;31m'
            'GUARDRAIL BLOCKED: "rm -r/-rf" outside .tmp/ requires explicit user confirmation.'
            '\033[0m'
        )
        print(msg, file=sys.stderr)
        sys.exit(2)
