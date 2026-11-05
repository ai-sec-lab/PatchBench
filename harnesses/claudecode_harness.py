"""Runs Claude Code through the Claude Agent SDK."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher,
                              ResultMessage, SystemMessage, ToolResultBlock, ToolUseBlock,
                              UserMessage)

from agent_base import AGENT_HOME, AGENT_USER, BUDGET_LIMIT, AgentHarness, main

#: Tool names whose arguments name a file the agent edited.
WRITE_TOOL_NAMES = {"Write", "Edit", "MultiEdit", "NotebookEdit",
                    "create", "str_replace", "insert", "undo_edit"}
#: Argument names that hold a file path.
PATH_FIELD_NAMES = {"path", "file_path", "filePath", "target_file",
                    "new_file_path", "old_file_path"}
#: Built-in tools that read or write files directly rather than through the shell.
FILE_TOOLS = "Read|Write|Edit|MultiEdit|NotebookEdit|Glob|Grep"


class ClaudeCodeHarness(AgentHarness):
    name = "claudecode"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        assert self.api_key is not None, "ANTHROPIC_API_KEY environment variable is not set."
        self.chat_history = self.log_dir / "claudecode-chat-log.jsonl"
        # A previous run's transcript would be read as this run's until the
        # session ends and replaces it.
        self.chat_history.unlink(missing_ok=True)
        # Repo files written so far, so a snapshot taken mid-run includes new
        # files; the transcript only arrives once the session has ended.
        self._written: set[str] = set()
        # Write-tool calls still waiting for their result: call id -> repo file.
        self._pending_writes: dict[str, str] = {}

    # -- running the agent --------------------------------------------------

    def invoke(self, prompt: str) -> None:
        """Run one SDK session, reporting spend as messages arrive."""
        asyncio.run(self._invoke_async(prompt))

    async def _invoke_async(self, prompt: str) -> None:
        options = ClaudeAgentOptions(
            model=self.model_name,
            permission_mode="default",
            cwd=self.repo_folder,
            # The SDK runs here as root and starts the CLI as the agent's user.
            user=AGENT_USER,
            env=self.agent_env(ANTHROPIC_API_KEY=self.api_key,
                               CLAUDE_CODE_EFFORT_LEVEL=self.effort),
            allowed_tools=["Read", "Write", "Edit", "Bash"],
            disallowed_tools={"WebSearch", "WebFetch"},
            hooks={"PreToolUse": [HookMatcher(matcher=FILE_TOOLS, hooks=[self._file_gate])]},
            max_budget_usd=BUDGET_LIMIT,
            max_buffer_size=10 * 1024 * 1024
        )

        session_id = None
        counted: dict[str, float] = {}
        # The commands Claude Code has moved to the background, as it last
        # listed them. When one ends it starts a turn of its own to report it,
        # so the session ends at the first result with none left running.
        background: list = []
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for message in client.receive_messages():
                print(message, flush=True)
                self._note_writes(message)
                if isinstance(message, SystemMessage) and message.subtype == "background_tasks_changed":
                    background = message.data.get("tasks") or []
                    continue
                if isinstance(message, ResultMessage):
                    session_id = message.session_id
                    if message.total_cost_usd is not None:
                        self.note_spend(message.total_cost_usd)
                    print(message.result, flush=True)
                    if not background or message.is_error or message.subtype != "success":
                        break
                    continue
                # Per-message costs arrive before the result; sum the distinct
                # ones so snapshots happen while the run is still going.
                mid = getattr(message, "message_id", None)
                cost = getattr(message, "total_cost_usd", None)
                if mid and cost is not None and counted.get(mid) != cost:
                    counted[mid] = cost
                    self.note_spend(sum(counted.values()))

        if session_id:
            self._save_transcript(session_id)

    async def _file_gate(self, input_data, _tool_use_id, _context) -> dict:
        """Refuse a file-tool call outside the folders shared with the task container."""
        tool_input = input_data.get("tool_input", {})
        path = next((tool_input[key] for key in ("file_path", "path", "notebook_path")
                     if tool_input.get(key)), None)
        if self.file_allowed(path, input_data.get("cwd") or self.repo_folder):
            return {}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"{path}: No such file or directory",
        }}

    def _note_writes(self, message) -> None:
        """Collect repo files from write-tool calls as their results arrive."""
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name in WRITE_TOOL_NAMES:
                    path = self._inside_repo(block.input.get("file_path")
                                             or block.input.get("notebook_path"))
                    if path:
                        self._pending_writes[block.id] = path
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock) and block.tool_use_id in self._pending_writes:
                    path = self._pending_writes.pop(block.tool_use_id)
                    if not block.is_error:
                        self._written.add(path)

    def _save_transcript(self, session_id: str) -> None:
        """Copy the session transcript into the log directory."""
        found = sorted(Path(AGENT_HOME, ".claude", "projects").glob(f"*/{session_id}.jsonl"))
        if found:
            shutil.copy(found[0], self.chat_history)
        else:
            print(f"Claude chat history not found for session {session_id}", flush=True)

    # -- changed files ------------------------------------------------------

    def changed_files(self) -> list[str]:
        """Repo files written by a write tool: seen in the messages, or named in the transcript."""
        found: set[str] = set(self._written)
        if not self.chat_history.exists():
            return sorted(found)

        with open(self.chat_history) as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._collect_write_paths(event, found)
        return sorted(found)

    def _collect_write_paths(self, event, found: set[str]) -> None:
        """Walk one transcript event, keeping paths named by write tools."""
        stack = [event]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                name = node.get("name") or node.get("tool_name")
                if isinstance(name, str) and name in WRITE_TOOL_NAMES:
                    self._paths_in(node, found)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)

    def _paths_in(self, node, found: set[str]) -> None:
        """Add every repo path held in a path field under ``node``."""
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PATH_FIELD_NAMES:
                    resolved = self._inside_repo(value)
                    if resolved:
                        found.add(resolved)
                self._paths_in(value, found)
        elif isinstance(node, list):
            for item in node:
                self._paths_in(item, found)

    def _inside_repo(self, value) -> str | None:
        """Absolute path for ``value`` if it names a non-markdown repo file."""
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = os.path.expanduser(value.strip())
        resolved = os.path.abspath(
            candidate if os.path.isabs(candidate)
            else os.path.join(self.repo_folder, candidate))
        try:
            if os.path.commonpath([self.repo_folder, resolved]) != self.repo_folder:
                return None
        except ValueError:
            return None
        return None if resolved.lower().endswith(".md") else resolved


if __name__ == "__main__":
    main(ClaudeCodeHarness)
