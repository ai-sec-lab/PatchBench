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
    },
    "claude-opus-5-5": {
        "input": 4, 
        "cached_input": 0.20, 
        "cache_write": 5.00, 
        "output": 20
    },
}

C_CPP_EXTENSIONS = {
    '.c', '.cpp', '.cc', '.cxx', '.c++',  # C/C++ source files
    '.h', '.hpp', '.hh', '.hxx', '.h++',  # Header files
    '.tpp', '.tcc', '.ipp',               # Template implementation files
    '.inl'                                # Inline files
}

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

CLAUDE_MODELS = [
    'claude-sonnet-4-5-20250929',
    'claude-sonnet-4-20250514',
    'claude-sonnet-4-6',
    'claude-opus-4-6',
    'claude-opus-4-8',
    'claude-opus-5-5',
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

# The environment variable holding the API key of each model's provider.
MODEL_API_KEYS = {
    **dict.fromkeys(OPENAI_NO_REASONING_MODELS + OPENAI_REASONING_MODELS + OPENAI_RESPONSE_MODELS,
                    "OPENAI_API_KEY"),
    **dict.fromkeys(CLAUDE_MODELS, "ANTHROPIC_API_KEY"),
    **dict.fromkeys(GEMINI_NO_REASONING_MODELS + GEMINI_REASONING_MODELS, "GEMINI_API_KEY"),
}

# The API key each agent reads. OpenHands serves several providers, so it reads
# the one of its model's provider (MODEL_API_KEYS).
AGENT_API_KEYS = {"claudecode": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY"}

# Effort levels Claude Code accepts (CLAUDE_CODE_EFFORT_LEVEL), chosen with
# `patchbench infer --effort`. OpenHands and Codex keep their own setting.
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]
DEFAULT_EFFORT = "xhigh"

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
    'claude-opus-5-5': 'claude-opus-5-5',
    'claude-opus-4-8': 'claude-opus-4-8',
    'claude-opus-4-6': 'claude-opus-4-6',
    'claude-sonnet-4-6': 'claude-sonnet-4-6',
    'claude-sonnet-4-5': 'claude-sonnet-4-5-20250929',
    'claude-sonnet-4': 'claude-sonnet-4-20250514',

    # gemini
    'gemini-3.5-flash': 'gemini-3.5-flash',
    'gemini-3.1-pro': 'gemini-3.1-pro-preview',
    'gemini-2.5-pro': 'gemini-2.5-pro',
    'gemini-2-flash': 'gemini-2.0-flash',
    'gemini-1.5-flash': 'gemini-1.5-flash',
    'gemini-1.5-pro': 'gemini-1.5-pro',

}
