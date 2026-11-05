"""Runs Codex through ``codex exec``."""

import json
import os
import shutil
import subprocess
import threading

from pathlib import Path

from agent_base import AGENT_HOME, AgentHarness, AgentUnavailable, main
from constants import MODEL_PRICING

#: How often the rollout logs are checked for newly written records.
POLL_INTERVAL_SECONDS = 1
#: How long codex gets to shut down cleanly when stopped at the budget.
STOP_GRACE_SECONDS = 10


class CodexHarness(AgentHarness):
    name = "codex"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pricing = MODEL_PRICING[self.model_name]
        self.codex_home = Path(AGENT_HOME) / ".codex"
        self._changed: set[str] = set()
        self._changed_lock = threading.Lock()

    def _install_config(self) -> None:
        """Copy ``codex_config/config.toml`` into the agent's codex home."""
        source = Path(__file__).parent / "codex_config" / "config.toml"
        home = Path(self.on_disk(self.codex_home))
        home.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, home / "config.toml")
        else:
            print(f"note: no codex config at {source}", flush=True)

    # -- running the agent --------------------------------------------------

    def invoke(self, prompt: str) -> None:
        """Log in, then run ``codex exec`` while polling its spend."""
        self._install_config()
        key = os.environ.get("OPENAI_API_KEY", "")
        env = self.agent_env(CODEX_HOME=str(self.codex_home), OPENAI_API_KEY=key)
        login = subprocess.run(["codex", "login", "--with-api-key"], input=key, text=True,
                               env=env, check=False, **self.as_agent())
        if login.returncode:
            raise AgentUnavailable("login unsuccessful")

        print(prompt)
        command = [
            "codex",
            "--ask-for-approval", "never",
            "exec",
            "--json",
            "--model", self.model_name,
            "--config", 'model_reasoning_effort="medium"',
            "--config", 'web_search="disabled"',
            "--cd", self.repo_folder,
            "--sandbox", "danger-full-access",
            prompt,
        ]

        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True,
                                errors="ignore", env=env, **self.as_agent())
        stop = threading.Event()
        reader = threading.Thread(target=self._read_events, args=(proc,), daemon=True)
        monitor = threading.Thread(target=self._watch_spend, args=(proc, stop),
                                   daemon=True)
        reader.start()
        monitor.start()
        try:
            proc.wait()
        finally:
            stop.set()
            monitor.join()
            reader.join(timeout=30)
            self._save_rollouts()

    def _read_events(self, proc) -> None:
        """Collect edited paths while codex is still running, for snapshots."""
        for line in proc.stdout:
            paths = self._paths_in_event(line)
            if paths:
                with self._changed_lock:
                    self._changed.update(paths)

    def _watch_spend(self, proc, stop: threading.Event) -> None:
        """Price each new token count in the rollout logs and kill codex at the budget.

        Codex appends a ``token_count`` record after every model response, so
        spend is checked each time it changes, as OpenHands reports it.
        """
        offsets: dict[str, int] = {}
        totals: dict[str, dict] = {}
        while not stop.is_set() and proc.poll() is None:
            new = False
            for path in self._rollout_paths():
                for usage in self._new_token_usages(path, offsets):
                    totals[path] = usage
                    new = True
            if new and self.note_spend(sum(map(self._price, totals.values()))):
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=STOP_GRACE_SECONDS)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                return
            if stop.wait(POLL_INTERVAL_SECONDS):
                return

    def _price(self, usage: dict) -> float:
        """Dollar cost of one rollout's running token totals."""
        p = self.pricing
        uncached = usage["input_tokens"] - usage["cached_input_tokens"]
        return (uncached * p["input"]
                + usage["cached_input_tokens"] * p["cached_input"]
                + usage["output_tokens"] * p["output"]) / 1e6

    # -- rollout logs -------------------------------------------------------

    @property
    def _sessions_dir(self) -> str:
        return str(self.codex_home / "sessions")

    def _rollout_paths(self) -> list[str]:
        if not os.path.isdir(self._sessions_dir):
            return []
        found = subprocess.run(["find", self._sessions_dir, "-type", "f",
                                "-name", "rollout*.jsonl", "-print0"],
                               check=False, capture_output=True)
        return [p.decode("utf-8") for p in found.stdout.split(b"\0") if p]

    @staticmethod
    def _new_token_usages(path: str, offsets: dict[str, int]) -> list[dict]:
        """Token totals from the records appended to ``path`` since it was last read.

        Only complete lines are taken; one codex is still writing waits for the
        next read.
        """
        with open(path, "rb") as handle:
            handle.seek(offsets.get(path, 0))
            data = handle.read()
        complete = data[:data.rfind(b"\n") + 1]
        offsets[path] = offsets.get(path, 0) + len(complete)
        usages = []
        for raw in complete.splitlines():
            try:
                payload = json.loads(raw).get("payload", {})
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "token_count" and payload.get("info"):
                usages.append(payload["info"]["total_token_usage"])
        return usages

    def _save_rollouts(self) -> None:
        """Copy the rollout logs into the log directory."""
        for path in self._rollout_paths():
            subprocess.run(["cp", path, str(self.log_dir)], check=False)

    # -- changed files ------------------------------------------------------

    @staticmethod
    def _paths_in_event(line: str) -> list[str]:
        """Paths named by one JSON event line, if it reports a file change."""
        line = line.strip()
        if not line:
            return []
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Anything non-JSON that leaks into stdout is not an event.
            return []
        if event.get("type") != "item.completed":
            return []
        item = event.get("item", {})
        if item.get("type") != "file_change":
            return []
        return [change.get("path", "") for change in item.get("changes", [])]

    def changed_files(self) -> list[str]:
        """Paths named by the ``file_change`` events codex printed."""
        with self._changed_lock:
            return sorted(p for p in self._changed if p)


if __name__ == "__main__":
    main(CodexHarness)
