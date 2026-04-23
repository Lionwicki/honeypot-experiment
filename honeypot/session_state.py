"""
session_state.py — Per-session virtual OS state for the LLM honeypot.

Each SSH connection gets its own SessionState instance.
The state is passed into the prompt builder on every command so the LLM
always knows where it is in the fake filesystem.
"""

import json
from dataclasses import dataclass, field
from typing import Optional


# Default fake filesystem — expand as needed
DEFAULT_FILESYSTEM: dict = {
    "/": ["bin", "boot", "etc", "home", "root", "tmp", "usr", "var"],
    "/home": ["user"],
    "/home/user": ["notes.txt", ".bash_history", ".bashrc"],
    "/root": [".bash_history", ".bashrc", ".ssh"],
    "/root/.ssh": ["authorized_keys"],
    "/etc": ["passwd", "shadow", "hosts", "hostname", "ssh", "cron.d", "apt"],
    "/etc/ssh": ["sshd_config", "ssh_config"],
    "/tmp": [],
    "/var": ["log", "www", "mail"],
    "/var/log": ["auth.log", "syslog", "kern.log"],
    "/var/www": ["html"],
    "/var/www/html": ["index.html"],
}

DEFAULT_ENV: dict = {
    "USER": "root",
    "HOME": "/root",
    "SHELL": "/bin/bash",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "TERM": "xterm-256color",
    "LANG": "en_US.UTF-8",
}


@dataclass
class CommandRecord:
    command: str
    output: str


@dataclass
class SessionState:
    hostname: str = "webserver-prod"
    os_description: str = "Ubuntu 22.04.3 LTS"
    cwd: str = "/root"
    filesystem: dict = field(default_factory=lambda: dict(DEFAULT_FILESYSTEM))
    env: dict = field(default_factory=lambda: dict(DEFAULT_ENV))
    history: list = field(default_factory=list)  # list of CommandRecord
    max_history: int = 15  # keep last N turns in prompt (context pruning)

    def record(self, command: str, output: str) -> None:
        """Append a completed command+output pair to history."""
        self.history.append(CommandRecord(command=command, output=output))

    def pruned_history(self) -> list[CommandRecord]:
        """Return only the most recent entries to stay within context budget."""
        return self.history[-self.max_history:]

    def _resolve_path(self, path: str) -> str:
        """Resolve a path from the LLM delta — join relative paths with cwd."""
        if path.startswith("/"):
            return path
        return f"{self.cwd.rstrip('/')}/{path}"

    def apply_state_delta(self, delta: Optional[dict]) -> None:
        """
        Apply a state change dict parsed from the LLM response.

        Expected delta format (all keys optional):
        {
            "cwd": "/tmp",
            "new_files": {"/tmp/malware.sh": null},   # null = it's a file, not a dir
            "new_dirs": ["/tmp/work"],
            "deleted": ["/tmp/old.txt"],
            "env": {"EDITOR": "vim"}
        }
        """
        if not delta:
            return

        if "cwd" in delta:
            self.cwd = delta["cwd"]

        if "new_files" in delta:
            for path, _ in delta["new_files"].items():
                path = self._resolve_path(path)
                parent = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
                name = path.rstrip("/").split("/")[-1]
                self.filesystem.setdefault(parent, [])
                if name not in self.filesystem[parent]:
                    self.filesystem[parent].append(name)

        if "new_dirs" in delta:
            for path in delta["new_dirs"]:
                path = self._resolve_path(path)
                parent = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
                name = path.rstrip("/").split("/")[-1]
                self.filesystem.setdefault(parent, [])
                if name not in self.filesystem[parent]:
                    self.filesystem[parent].append(name)
                self.filesystem.setdefault(path, [])

        if "deleted" in delta:
            for path in delta["deleted"]:
                path = self._resolve_path(path)
                parent = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
                name = path.rstrip("/").split("/")[-1]
                if parent in self.filesystem and name in self.filesystem[parent]:
                    self.filesystem[parent].remove(name)

        if "env" in delta:
            self.env.update(delta["env"])

    def to_prompt_summary(self) -> str:
        """
        Compact representation of current state for injection into the LLM prompt.

        Token budget matters — a full filesystem JSON dump (~300 tokens) causes
        gemma3:4b to time out on ls/cd commands as it tries to cross-reference the
        entire tree. Instead we provide:
          - CWD with its immediate contents (what ls would show)
          - A flat list of known paths (so the model knows what directories exist)
          - ENV vars on a single line
        """
        env_str = " ".join(f"{k}={v}" for k, v in self.env.items())
        cwd_contents = self.filesystem.get(self.cwd, [])
        known_paths = " ".join(sorted(self.filesystem.keys()))
        return (
            f"OS: {self.os_description} | hostname: {self.hostname}\n"
            f"CWD: {self.cwd}  contents: {cwd_contents}\n"
            f"ENV: {env_str}\n"
            f"Known filesystem paths: {known_paths}"
        )
