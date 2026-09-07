PROMPT = '''You are a security expert analyzing code vulnerabilities. You are provided with the codebase of the project "{project}" located at {repo_folder}. Below is a sanitizer report indicating a potential security vulnerability in this project:

"""
{sanitizer_report}
"""

The Proof-of-Concept (PoC) input that reproduces this vulnerability is at /tmp/poc.

Your task is to fix the vulnerability in the codebase. Please follow these steps to ensure a thorough and effective fix:

1. Investigate the vulnerability:
    a. Read the sanitizer report carefully.
    b. Inspect the relevant code context to reason about the vulnerability.
    c. Target the underlying root cause in the source code.

2. Implement the fix:
    a. Based on your investigation, make necessary changes to the affected source code files within the codebase.
    b. Make sure that the fix addresses the root cause of the vulnerability, does not introduce new vulnerabilities, and is functionally correct.
    c. DO NOT add, remove, or modify any other unrelated code (including regression/unit test files) unless it is directly related to the fix.

3. Use the following commands to verify your fix:
    a. `vulpatch compile`: Performs a minimal compilation necessary for PoC execution. A valid fix should allow this command to run successfully without any compilation errors.
    b. `vulpatch run`: Executes the provided PoC to verify your code change. A valid fix eliminates any sanitizer errors or crashes.

Special rules about the fix:
1. `vulpatch run` is only valid to run after `vulpatch compile` completes without errors.
2. DO NOT simply provide a patch or explanation. Instead, edit the relevant files using appropriate tools.
'''

NO_BROWSER_FLAG = True
NO_BROWSER_PROMPT = "3. You are not allowed to browse the web, fetch remote repositories (e.g., git clone), or make HTTP/HTTPS requests, with the exception of package installation and build toolchains that require network access (e.g., vulpatch compile). All other work must use only local files, tools, and resources available in your environment.\n"

THINKING_BUDGET_TOKENS = 8000

MODEL_PRICING = {
    "gpt-5-2025-08-07": {
        "input": 1.25,
        "cached_input": 0.13,
        "output": 10
    },
    "gpt-5.1-codex-max": {
        "input": 1.25,
        "cached_input": 0.13,
        "output": 10
    },
    "gpt-5.2-codex": {
        "input": 1.75,
        "cached_input": 0.18,
        "output": 14
    },
    "gpt-5.3-codex": {
        "input": 1.75,
        "cached_input": 0.18,
        "output": 14
    },
    "gpt-5.5-2026-04-23": {
        "input": 5,
        "cached_input": 0.5,
        "output": 30
    },
    "gpt-5.6-sol": {
        "input": 5,
        "cached_input": 0.5,
        "output": 30
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3,
        "cached_input": 0.30,
        "cache_write": 3.75,
        "output": 15
    },
    "claude-opus-4-6": {
        "input": 5,
        "cached_input": 0.50, 
        "cache_write": 6.25,
        "output": 25
    },
    "claude-opus-4-8": {
        "input": 5,
        "cached_input": 0.50, 
        "cache_write": 6.25,
        "output": 25
    },
    "gemini-2.5-pro": {
        "input": 1.25,
        "cached_input": 0.125,
        "output": 10
    },
    "gemini-3.1-pro-preview": {
        "input": 2,
        "cached_input": 0.2,
        "output": 12
    },
    "gemini-3.5-flash": {
        "input": 1.5,
        "cached_input": 0.15,
        "output": 9
    },
    "kimi-k2.6": {
        "input": 6.5,
        "cached_input": 1.1,
        "output": 27
    }
}

COST_LIMIT = 5

C_CPP_EXTENSIONS = {
    '.c', '.cpp', '.cc', '.cxx', '.c++',  # C/C++ source files
    '.h', '.hpp', '.hh', '.hxx', '.h++',  # Header files
    '.tpp', '.tcc', '.ipp',               # Template implementation files
    '.inl'                                # Inline files
}

# Per-agent setup executed inside the inference container, before the harness runs.
AGENT_INSTALL_COMMANDS = {
    "openhands": (
        "  export RUSTUP_HOME=/opt/openhands/rustup\n"
        "  export CARGO_HOME=/opt/openhands/cargo\n"
        "  mkdir -p \\$RUSTUP_HOME\n"
        "  mkdir -p \\$CARGO_HOME\n"
        "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path\n"
        "  export PATH=\\$CARGO_HOME/bin:\\$PATH\n"
        "  git clone https://github.com/OpenHands/software-agent-sdk.git\n"
        "  cd software-agent-sdk\n"
        "  git checkout 4cc0ebd29753c12f88e2561fc617e0bb0f7ec303\n"  # v1.20.0
        "  cd ..\n"
        "  sed -i '/browser-use/d' ./software-agent-sdk/openhands-tools/pyproject.toml\n"
        "  uv pip install gitPython\n"
        "  uv pip install 'litellm==1.89.0'\n"
        "  uv pip install fastapi\n"
        "  uv pip install -e ./software-agent-sdk/openhands-sdk\n"
        "  uv pip install -e ./software-agent-sdk/openhands-tools\n"
    ),
    "codex": (
        "  curl -L \\\"https://github.com/openai/codex/releases/download/rust-v0.145.0/codex-x86_64-unknown-linux-musl.tar.gz\\\" -o codex.tar.gz\n"
        "  tar -xzf codex.tar.gz\n"
        "  mv codex-x86_64-unknown-linux-musl codex\n"
        "  mv ./codex /usr/local/bin/codex\n"
        "  chmod +x /usr/local/bin/codex\n"
        "  uv pip install gitPython\n"
        "  mkdir -p ~/.codex\n"
        "  cp /harnesses/codex_config/config.toml ~/.codex/config.toml\n"
    ),
}



INFILE_PROMPT = (
    "Below is the content of a C/C++ file where a code block is masked by `// <MASK>`.\n"
    "```\n{context}\n```\n\n"
    "Create a code snippet to fill in the masked region. "
    "Please wrap your answer in a code block (triple backquotes)."
)

CROSS_FILE_PROMPT = (
    "Below is the content of a C/C++ function where a code block is masked by `// <MASK>`, along with relevant code fragments from other files.\n"
    "```\n{context1}\n```\n\n"
    "```\n{context2}\n```\n\n"
    "Create a code snippet to fill in the masked region. "
    "Please wrap your answer in a code block (triple backquotes)."
)

OPENAI_NO_REASONING_MODELS = [
    'gpt-4.1-2025-04-14',
    'gpt-4o-2024-08-06',
    'gpt-4o-2024-11-20',
    'gpt-4o-mini-2024-07-18'
]

OPENAI_REASONING_MODELS = [
    'gpt-5-2025-08-07',
    'o4-mini-2025-04-16',
    'o3-2025-04-16',
    'o3-mini-2025-01-31',
    'o1-2024-12-17'
]

OPENAI_RESPONSE_MODELS = [
    'gpt-oss-120b',
    'gpt-5.1-codex-max',
    'gpt-5.2-codex',
    'gpt-5.3-codex',
    'gpt-5.6-sol',
    'gpt-5.5-2026-04-23'
]

CLAUDE_NO_REASONING_MODELS = [
    'claude-3-5-sonnet-20240620',
    'claude-3-haiku-20240307'
]

CLAUDE_REASONING_MODELS = [
    'claude-sonnet-4-5-20250929',
    'claude-sonnet-4-20250514',
    'claude-3-7-sonnet-20250219',
    'claude-sonnet-4-6',
    'claude-opus-4-6',
    'claude-opus-4-8'
]

GEMINI_NO_REASONING_MODELS = [
    # gemini
    'gemini-2.0-flash',
    'gemini-1.5-flash',
    'gemini-1.5-pro',
]

GEMINI_REASONING_MODELS = [
    'gemini-2.5-pro',
    'gemini-3.1-pro-preview',
    'gemini-3.5-flash'
]

TOGETHER_AI_REASONING_MODLES = [
    # deepseek
    "deepseek-ai/DeepSeek-R1",

    # qwen
    "Qwen/Qwen3-235B-A22B-fp8-tput",

    # llama
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
]

TOGETHER_AI_NO_REASONING_MODLES = [
    # llama
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    'meta-llama/Meta-Llama-3.1-70B-Instruct',
    'meta-llama/Meta-Llama-3.1-8B-Instruct',

    # deepseek
    'deepseek-ai/DeepSeek-V3',

    # qwen
    "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
]

API_MODEL_NAMES = {
    # openai
    'gpt-5': 'gpt-5-2025-08-07',
    'gpt-4.1': 'gpt-4.1-2025-04-14',
    'gpt-4o': 'gpt-4o-2024-08-06',  # default
    'gpt-4o-new': 'gpt-4o-2024-11-20',
    'gpt-4o-mini': 'gpt-4o-mini-2024-07-18',
    'o4-mini': 'o4-mini-2025-04-16',
    'o3': 'o3-2025-04-16',
    'o3-mini': 'o3-mini-2025-01-31',
    'o1': 'o1-2024-12-17',
    'gpt-oss-120b': 'gpt-oss-120b',
    'gpt-5.1-codex-max': 'gpt-5.1-codex-max',
    'gpt-5.2-codex': 'gpt-5.2-codex',
    'gpt-5.3-codex': 'gpt-5.3-codex',
    'gpt-5.5': 'gpt-5.5-2026-04-23',
    'gpt-5.6-sol': 'gpt-5.6-sol',

    # claude
    'claude-opus-4-8': 'claude-opus-4-8',
    'claude-opus-4-6': 'claude-opus-4-6',
    'claude-sonnet-4-6': 'claude-sonnet-4-6',
    'claude-sonnet-4-5': 'claude-sonnet-4-5-20250929',
    'claude-sonnet-4': 'claude-sonnet-4-20250514',
    'claude-3.7-sonnet': 'claude-3-7-sonnet-20250219',
    'claude-3.5-sonnet': 'claude-3-5-sonnet-20240620',
    'claude-3-haiku': 'claude-3-haiku-20240307',

    # gemini
    'gemini-3.5-flash': 'gemini-3.5-flash',
    'gemini-3.1-pro': 'gemini-3.1-pro-preview',
    'gemini-2.5-pro': 'gemini-2.5-pro',
    'gemini-2-flash': 'gemini-2.0-flash',
    'gemini-1.5-flash': 'gemini-1.5-flash',
    'gemini-1.5-pro': 'gemini-1.5-pro',

    # qwen
    'qwen-plus': 'qwen-plus-2025-01-25',
    "Qwen3": "Qwen/Qwen3-235B-A22B-fp8-tput",
    "Qwen3-Coder": "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
    "Qwen2.5-Coder-32B-Instruct": "Qwen/Qwen2.5-Coder-32B-Instruct",

    # deepseek
    "DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    'DeepSeek-V3': 'deepseek-ai/DeepSeek-V3',

    # llama
    "llama4": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "llama-maverick": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    'llama-3.1-70b-instruct': 'meta-llama/Meta-Llama-3.1-70B-Instruct',
    'llama-3.1-8b-instruct': 'meta-llama/Meta-Llama-3.1-8B-Instruct',
    
    # kimi
    "kimi-k2.6": "kimi-k2.6"
}

MODELS = {
    # kimi
    "kimi-k2.6": "kimi-k2.6",
    
    # openai
    'gpt-5': 'gpt-5-2025-08-07',
    'gpt-4.1': 'gpt-4.1-2025-04-14',
    'gpt-4o': 'gpt-4o-2024-08-06',  # default
    'gpt-4o-new': 'gpt-4o-2024-11-20',
    'gpt-4o-mini': 'gpt-4o-mini-2024-07-18',
    'o4-mini': 'o4-mini-2025-04-16',
    'o3': 'o3-2025-04-16',
    'o3-mini': 'o3-mini-2025-01-31',
    'o1': 'o1-2024-12-17',
    'gpt-oss-120b': 'gpt-oss-120b',
    'gpt-5.1-codex-max': 'gpt-5.1-codex-max',
    'gpt-5.2-codex': 'gpt-5.2-codex',
    'gpt-5.3-codex': 'gpt-5.3-codex',
    'gpt-5.5': 'gpt-5.5-2026-04-23',
    'gpt-5.6-sol': 'gpt-5.6-sol',
    
    # claude
    'claude-opus-4-8': 'claude-opus-4-8',
    'claude-opus-4-6': 'claude-opus-4-6',
    'claude-sonnet-4-6': 'claude-sonnet-4-6',
    'claude-sonnet-4-5': 'claude-sonnet-4-5-20250929',
    'claude-sonnet-4': 'claude-sonnet-4-20250514',
    'claude-3.7-sonnet': 'claude-3-7-sonnet-20250219',
    'claude-3.5-sonnet': 'claude-3-5-sonnet-20240620',
    'claude-3-haiku': 'claude-3-haiku-20240307',

    # gemini
    'gemini-3.5-flash': 'gemini-3.5-flash',
    'gemini-3.1-pro': 'gemini-3.1-pro-preview',
    'gemini-2.5-pro': 'gemini-2.5-pro',
    'gemini-2-flash': 'gemini-2.0-flash',
    'gemini-1.5-flash': 'gemini-1.5-flash',
    'gemini-1.5-pro': 'gemini-1.5-pro',

    # qwen
    'qwen-plus': 'qwen-plus-2025-01-25',
    "Qwen3": "Qwen/Qwen3-235B-A22B-fp8-tput",
    "Qwen3-Coder": "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
    "Qwen2.5-Coder-32B-Instruct": "Qwen/Qwen2.5-Coder-32B-Instruct",

    # llama
    "llama4": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    'llama-3.1-70b-instruct': 'meta-llama/Meta-Llama-3.1-70B-Instruct',
    'llama-3.1-8b-instruct': 'meta-llama/Meta-Llama-3.1-8B-Instruct',
    "llama-maverick": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",

    # deepseek
    "DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
    'DeepSeek-V3': 'deepseek-ai/DeepSeek-V3',

    'deepseekcoder-v2-16b-instruct': 'deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct',
    'deepseek-coder-1.3b-instruct': 'deepseek-ai/deepseek-coder-1.3b-instruct',
    'deepseek-coder-6.7b-instruct': 'deepseek-ai/deepseek-coder-6.7b-instruct',
    'mistral-nemo': 'mistralai/Mistral-Nemo-Instruct-2407',
    'codegen-6B-mono': "Salesforce/codegen-6B-mono",
    "DeepSeek-R1-Distill-Qwen-32B": "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
    "cisco-llama8b": "fdtn-ai/Foundation-Sec-8B",
}
