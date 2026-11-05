#!/bin/bash
# The OpenHands SDK, pinned to the commit the benchmark was run with.
set -euo pipefail

OPENHANDS_SDK_COMMIT="33d8aa29c3078d074799e2fbf5e847aeb2d71360"   # v1.56.0

export CARGO_HOME=/opt/cargo RUSTUP_HOME=/opt/rustup
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
export PATH="/opt/cargo/bin:${PATH}"

git clone https://github.com/OpenHands/software-agent-sdk.git /opt/software-agent-sdk
git -C /opt/software-agent-sdk checkout "${OPENHANDS_SDK_COMMIT}"
sed -i '/browser-use/d' /opt/software-agent-sdk/openhands-tools/pyproject.toml

uv pip install 'litellm==1.93.0' 'fastapi==0.136.3' \
    -e /opt/software-agent-sdk/openhands-sdk \
    -e /opt/software-agent-sdk/openhands-tools
