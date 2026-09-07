import os
import json
import time
import shutil
from pathlib import Path
from git import Repo
import argparse
from openhands.sdk import LLM, Agent, Conversation
from openhands.tools.preset.default import get_default_tools
from openhands.sdk.event.llm_convertible.observation import ObservationEvent
from constants import *


# Openhands has its own configure file, need to map the exact same model name
MODEL_MAPPINGS = {
    'gpt-4.1-2025-04-14': 'gpt-4.1',
    'o4-mini-2025-04-16': 'o4-mini',
    'o3-2025-04-16': 'o3',
    'gemini-3.1-pro-preview': 'gemini/gemini-3.1-pro-preview',
    'gemini-3.5-flash': 'gemini/gemini-3.5-flash',
    'kimi-k2.6': 'openai/kimi-k2.6',
    'gpt-5.6-sol': 'openai/gpt-5.6-sol',
}


WRITE_COMMANDS = {"create", "str_replace", "insert", "undo_edit"}


# Total dollar budget allowed for a single run. The conversation is terminated
# once the accumulated cost crosses this value.
BUDGET_LIMIT = 30
# A diff snapshot is taken every time the cost crosses a multiple of this value.
COST_STEP = 5


class OpenhandsSnapshotRunner:
    def __init__(self, model_name):
        self.log_dir = f"/.openhands/"
        os.makedirs(self.log_dir, exist_ok=True)

        input_cost = MODEL_PRICING[model_name]["input"] / 1000000
        output_cost = MODEL_PRICING[model_name]["output"] / 1000000
        self.pricing = MODEL_PRICING[model_name]

        if model_name in MODEL_MAPPINGS:
            self.model_name = MODEL_MAPPINGS[model_name]
        else:
            self.model_name = model_name

        reasoning_effort = "medium"

        if model_name in OPENAI_NO_REASONING_MODELS or model_name in OPENAI_REASONING_MODELS or model_name in OPENAI_RESPONSE_MODELS:
            key = os.environ["OPENAI_API_KEY"]
        elif model_name in CLAUDE_NO_REASONING_MODELS or model_name in CLAUDE_REASONING_MODELS:
            key = os.environ["ANTHROPIC_API_KEY"]
        elif model_name in GEMINI_NO_REASONING_MODELS or model_name in GEMINI_REASONING_MODELS:
            key = os.environ["GEMINI_API_KEY"]
        else:
            raise Exception("Model not supported!")
        
        os.environ["LLM_API_KEY"] = key
        

        self.llm_config = LLM(
            model=self.model_name,
            api_key=key,
            reasoning_effort=reasoning_effort,
            base_url="https://us.api.openai.com/v1"   # comment it when not using OpenAI models
        )

        self.agent_config = Agent(
            llm=self.llm_config,
            tools=get_default_tools(enable_browser=False)
        )

    @staticmethod
    def init(repo_dir):
        shutil.rmtree(f"{repo_dir}/.git")
        repo = Repo.init(repo_dir)
        return repo

    @staticmethod
    def commit(repo: Repo, file=None):
        msg = f"Auto-commit on {time.strftime('%Y-%m-%d %H:%M:%S')}"
        repo.git.commit("--allow-empty", "--no-verify", "-m", msg)
        return repo.head.commit.hexsha

    @staticmethod
    def diff_between(repo: Repo, base_sha: str, head_sha: str):
        cmd = [
            "git", "diff", base_sha, head_sha,
        ]

        patch_text = repo.git.execute(
            cmd,
            stdout_as_string=True,
            strip_newline_in_stdout=False,   # <-- key bit
        )

        return patch_text

    @staticmethod
    def get_file_changed(conversation):
        changes = []
        for ev in conversation.state.events:
            if isinstance(ev, ObservationEvent) and ev.tool_name == "file_editor":
                obs = ev.observation.model_dump()
                if obs.get("is_error"):
                    continue
                if obs.get("command") in WRITE_COMMANDS:
                    path = obs.get("path")
                    if path:
                        changes.append(path)
        changes = list(set(changes))
        return changes

    def run(self, id, repo_folder, out_base):
        """Run openhands and take a diff snapshot every ``COST_STEP`` dollars.

        Returns ``(final_diff, budget_exhausted)``. ``final_diff`` is always the
        complete ``mask_id..HEAD`` diff and is meant to be written as the plain
        ``.diff`` regardless of how the run ended. ``budget_exhausted`` is True
        when the run was terminated for crossing ``BUDGET_LIMIT`` (in which case
        the per-threshold snapshots, including ``_{BUDGET_LIMIT}.diff``, were
        also written).
        """

        repo_base = self.init(repo_folder)
        repo_base.git.add(A=True)
        mask_id = self.commit(repo_base)

        metadata = json.loads(Path("/harnesses/metadata.json").read_text())
        sanitizer_report = metadata[id]["sanitizer_report"]
        project = metadata[id]["project"]

        if NO_BROWSER_FLAG:
            prompt = PROMPT.format(
                project=project,
                repo_folder=repo_folder,
                sanitizer_report=sanitizer_report
            ) + NO_BROWSER_PROMPT
        else:
            prompt = PROMPT.format(
                project=project,
                repo_folder=repo_folder,
                sanitizer_report=sanitizer_report
            )

        api_key = os.getenv("LLM_API_KEY")
        assert api_key is not None, "LLM_API_KEY environment variable is not set."

        # Snapshot thresholds: 5, 10, ..., BUDGET_LIMIT.
        thresholds = list(range(COST_STEP, BUDGET_LIMIT + 1, COST_STEP))
        # Index into `thresholds` of the next snapshot to take.
        next_idx = 0
        budget_exhausted = False

        def _stage_changed_files():
            for f in self.get_file_changed(conversation):
                if f.startswith(repo_folder) and not f.endswith(".md"):
                    try:
                        repo_base.git.add(f)
                    except Exception as e:
                        print(
                            f"Error occurred while adding file {f}: {e}", flush=True)

        def _take_snapshot(threshold):
            """Commit the currently-known changes and write a snapshot diff."""
            _stage_changed_files()
            self.commit(repo_base)
            diff = self.diff_between(repo_base, mask_id, "HEAD")
            snapshot_path = f"{out_base}_{threshold}.diff"
            Path(snapshot_path).write_text(diff, errors="ignore")
            print(f"Snapshot at {threshold} dollars saved to {snapshot_path}",
                  flush=True)

        # The callback runs synchronously in the conversation loop (single
        # thread), so the snapshot bookkeeping needs no locking. A single event
        # may cross several thresholds at once, hence the while loop.
        def budget_guard(_event):
            nonlocal next_idx, budget_exhausted
            u = conversation.conversation_stats.get_combined_metrics().accumulated_token_usage
            if u is None:
                spend = 0.0
            else:
                p = self.pricing
                uncached = max(u.prompt_tokens - u.cache_read_tokens, 0)
                spend = (uncached            * p["input"]
                        + u.cache_read_tokens  * p["cached_input"]
                        + u.cache_write_tokens * p.get("cache_write", 0)
                        + u.completion_tokens  * p["output"]) / 1_000_000
            print(f"Current usage: {spend:.2f} dollars", flush=True)

            while next_idx < len(thresholds) and spend >= thresholds[next_idx]:
                threshold = thresholds[next_idx]
                _take_snapshot(threshold)
                next_idx += 1

                if threshold >= BUDGET_LIMIT:
                    budget_exhausted = True
                    raise ValueError(
                        f"Budget exceeded: ${spend:.4f} >= ${BUDGET_LIMIT}")

        conversation = Conversation(
            agent=self.agent_config,
            workspace=os.path.abspath(repo_folder),
            persistence_dir=self.log_dir,
            callbacks=[budget_guard]
        )

        conversation.send_message(prompt)

        try:
            conversation.run()
        except ValueError as e:
            print(str(e))
            print(
                f"Openhands run terminated after exceeding {BUDGET_LIMIT} dollars usage.", flush=True)
        except Exception as e:
            print(str(e))

        # Build the final diff from the complete set of changes and let the
        # caller write the plain .diff. This happens whether the run finished
        # naturally or was terminated for exceeding the budget; in the latter
        # case the per-threshold snapshots have already been written too.
        changed_files = self.get_file_changed(conversation)
        conversation.close()
        for f in changed_files:
            if f.startswith(repo_folder) and not f.endswith(".md"):
                try:
                    repo_base.git.add(f)
                except Exception as e:
                    print(
                        f"Error occurred while adding file {f}: {e}", flush=True)

        if not changed_files:
            print("No files were changed by the agent.", flush=True)
            status_out = repo_base.git.status("--porcelain")

            for line in status_out.splitlines():
                if len(line) < 4:
                    continue
                status_code = line[:2]
                path_part = line[3:]
                if " -> " in path_part:
                    path_part = path_part.split(" -> ", 1)[1]

                file_path = os.path.join(repo_folder, path_part)
                # Only stage modified source files in the fallback path.
                if (
                    "M" in status_code
                    and "A" not in status_code
                    and "D" not in status_code
                    and "R" not in status_code
                    and "C" not in status_code
                    and "?" not in status_code
                    and file_path.startswith(repo_folder)
                    and Path(file_path).suffix.lower() in C_CPP_EXTENSIONS
                ):
                    repo_base.git.add(file_path)

        self.commit(repo_base)
        diff = self.diff_between(repo_base, mask_id, "HEAD")
        return diff, budget_exhausted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-name', type=str)
    parser.add_argument('--sanitizer_report', type=str)
    parser.add_argument('--repo-folder', type=str)
    # parser.add_argument('--changed-file', type=str)
    # Where to write the diff. The host owns the naming scheme.
    parser.add_argument('--out-base', type=str)
    args = parser.parse_args()

    out_base = args.out_base

    client = OpenhandsSnapshotRunner(args.model_name)
    final_diff, budget_exhausted = client.run(
        args.sanitizer_report, args.repo_folder, out_base)

    # Always save a final diff, whether or not the budget was exhausted.
    if final_diff is not None:
        Path(f'{out_base}.diff').write_text(final_diff, errors="ignore")


if __name__ == "__main__":
    main()
