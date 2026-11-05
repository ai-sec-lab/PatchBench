#!/bin/bash
# Codex's release package, as a local install has it: the codex program, the
# host that runs code-mode models' JavaScript `exec` tool, and the tools Codex
# puts on its commands' PATH (codex-path, with rg). All static musl binaries,
# so it needs no runtime of its own.
set -euo pipefail

CODEX_VERSION="rust-v0.163.0"

curl -fsSL "https://github.com/openai/codex/releases/download/${CODEX_VERSION}/codex-package-x86_64-unknown-linux-musl.tar.gz" \
    -o /tmp/codex-package.tar.gz
mkdir -p /opt/codex
tar -xzf /tmp/codex-package.tar.gz -C /opt/codex --no-same-owner
rm /tmp/codex-package.tar.gz
ln -s /opt/codex/bin/codex /usr/local/bin/codex
