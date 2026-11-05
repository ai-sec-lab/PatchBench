#!/bin/bash
# The Claude Agent SDK, which ships the Claude Code binary it runs.
set -euo pipefail

CLAUDE_AGENT_SDK_VERSION="0.2.168"

uv pip install "claude-agent-sdk==${CLAUDE_AGENT_SDK_VERSION}"
