"""
ssh_handler.py — Minimal asyncssh-based SSH server wiring the LLM shell together.

This is a standalone SSH server — it does NOT depend on Cowrie.
For the thesis implementation you have two options:
  A) Use this file directly (simpler, full control)
  B) Hook into Cowrie by replacing HoneyPotSSHTransport's command handler

To run:
    pip install asyncssh
    python -m honeypot.ssh_handler

Generates a host key on first run (host_key.pem). In production use a pre-generated key.
"""

import asyncio
import logging
import os

import asyncssh

from .ollama_backend import query_ollama
from .prompt_builder import build_prompt
from .session_state import SessionState

logger = logging.getLogger(__name__)


def _split_commands(line: str) -> list[str]:
    """
    Split a shell line into individual sub-commands.

    Handles: &&, ||, ;, and simple pipes (|).
    Does not attempt full shell parsing — splits naively on operators
    outside of quoted strings, which is sufficient for honeypot purposes.

    Examples:
        "cd /tmp && touch evil.sh"  → ["cd /tmp", "touch evil.sh"]
        "ls; whoami"                → ["ls", "whoami"]
        "cat /etc/passwd | grep root" → ["cat /etc/passwd", "grep root"]
    """
    import re
    # Split on &&, ||, ;, or | — but not inside single/double quotes
    parts = re.split(r'(?<![\'"])\s*(?:&&|\|\||;|\|)\s*(?![\'"])', line)
    return [p.strip() for p in parts if p.strip()]


HOST_KEY_FILE = "host_key.pem"
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 2222          # use 22 in production (requires root or CAP_NET_BIND_SERVICE)
BANNER = "Ubuntu 22.04.3 LTS\r\n"
MAX_TURNS = 25  # hard cap per session — prevents hung automated attacker loops


class LLMShellSession(asyncssh.SSHServerSession):
    """One instance per connected SSH client."""

    def __init__(self):
        self._state = SessionState()
        self._input_buffer = ""
        self._chan = None
        self._turn_count = 0

    def connection_made(self, chan):
        self._chan = chan
        logger.info("New session from %s", chan.get_extra_info("peername"))

    def shell_requested(self):
        return True

    def data_received(self, data: str, datatype):
        """Called for every chunk of data the attacker sends."""
        for char in data:
            if char in ("\r", "\n"):
                self._chan.write("\r\n")
                self._handle_line(self._input_buffer.strip())
                self._input_buffer = ""
            elif char == "\x7f":  # backspace
                if self._input_buffer:
                    self._input_buffer = self._input_buffer[:-1]
                    self._chan.write("\b \b")
            else:
                self._input_buffer += char
                self._chan.write(char)  # echo

    def _handle_line(self, command: str) -> None:
        if not command:
            self._write_prompt()
            return

        self._turn_count += 1
        if self._turn_count > MAX_TURNS:
            self._chan.write("Connection closed by remote host.\r\n")
            self._chan.exit(0)
            return

        if command.strip() in ("exit", "logout"):
            self._chan.write("logout\r\n")
            self._chan.exit(0)
            return

        # Fix: split chained commands before sending to LLM.
        # A single LLM call for "cmd1 && cmd2" confuses smaller models and causes
        # generation loops / timeouts. We run each sub-command as its own LLM call
        # so state updates apply between them — more accurate and more reliable.
        for sub_command in _split_commands(command):
            prompt = build_prompt(self._state, sub_command)
            output, delta = query_ollama(prompt)

            self._state.apply_state_delta(delta)
            self._state.record(sub_command, output)

            if output:
                self._chan.write(output.replace("\n", "\r\n") + "\r\n")

        self._write_prompt()

    def _write_prompt(self) -> None:
        user = self._state.env.get("USER", "root")
        host = self._state.hostname
        cwd = self._state.cwd.replace(self._state.env.get("HOME", "/root"), "~")
        self._chan.write(f"{user}@{host}:{cwd}# ")

    def eof_received(self):
        self._chan.exit(0)


class LLMSSHServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True  # always require auth attempt (accept any password below)

    def password_auth_supported(self):
        return True

    def validate_password(self, username: str, password: str) -> bool:
        # Accept any login — this is a honeypot
        logger.info("Login attempt: user=%s password=%s", username, password)
        return True

    def session_requested(self):
        return LLMShellSession()


async def start_server():
    if not os.path.exists(HOST_KEY_FILE):
        logger.info("Generating new host key → %s", HOST_KEY_FILE)
        key = asyncssh.generate_private_key("ssh-rsa")
        key.write_private_key(HOST_KEY_FILE)

    await asyncssh.create_server(
        LLMSSHServer,
        host=LISTEN_HOST,
        port=LISTEN_PORT,
        server_host_keys=[HOST_KEY_FILE],
    )
    logger.info("LLM honeypot listening on %s:%d", LISTEN_HOST, LISTEN_PORT)
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_server())
