"""Runs the project's own unit tests against the patched build.

Both halves of the stage live here: the container script that runs a project's
suite, and the reading of that suite's output into a verdict.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from ..config.projects import unittest_commands, unittest_patterns
from .utils import (DockerScript, Job, ParseError, ProcOutput, Stage, Task,
                    remove_ansi, unquote_for_bash_c)


class UnitTests(Stage):
    """Applies the patch and runs the project's test suite.

    No rebuild happens first: each project's command drives its own build, so
    this stage measures whether the patch broke existing behaviour.
    """

    stage = "unittest"
    result_keys = ("unittest",)
    timeout = 6000
    retries = 5

    def script_path(self, task: Task) -> Path:
        return self.paths.script_dir(self.stage, task.id) / f"{task.slug}.sh"

    # -- setup --------------------------------------------------------------

    def build_scripts(self, task: Task) -> None:
        """Write the container script that runs this project's test suite."""
        project = self.project_of(task)
        script = DockerScript(
            image=task.image,
            name=self.container_name(task),
            volumes=[f"{self.paths.diff_dir(task.id)}:/patches"],
            env={"MAKEFLAGS": "-j8"},
        )
        script.write(
            self.script_path(task),
            DockerScript.limit_nproc()
            + DockerScript.locate_repo(project)
            + DockerScript.apply_patch(task.diff_name)
            + self.unittest_command(project)
            + "\n",
        )

    @staticmethod
    def unittest_command(project_name: str) -> str:
        """This project's test command, or a notice when it ships no tests."""
        command = unittest_commands.get(project_name.lower())
        return unquote_for_bash_c(command) if command else "echo 'NO UNIT TESTS'"

    def jobs_for(self, task: Task) -> list[Job]:
        script = self.script_path(task)
        return [Job(task, self.stage, ["/bin/bash", str(script)])] if script.is_file() else []

    # -- verdicts -----------------------------------------------------------

    def parse(self, task: Task, result_key: str, proc: ProcOutput) -> Any:
        """Read the project's test output into a pass/fail/skip breakdown."""
        stdout = remove_ansi(proc.stdout.decode(errors="ignore"))
        return SuiteOutput(self.project_of(task)).parse(stdout)


class SuiteOutput:
    """A pass/fail/skip breakdown read out of one project's test-suite output."""

    #: Statuses in the raw output, normalised onto the three result buckets.
    _PASS_WORDS = {"ok", "okay", "success", ".", "", "done", "passed"}
    _FAIL_WORDS = {"error", "e", "f", "fail", "not ok", "failed", "failure"}
    _SKIP_WORDS = {"?", "skipped"}

    def __init__(self, project_name: str) -> None:
        self.project = project_name.lower()

    def parse(self, stdout: str) -> dict[str, Any]:
        result: dict[str, Any] = {"pass": [], "fail": [], "skip": [], "total": None}

        special = self._SPECIAL_CASES.get(self.project)
        if special is not None:
            special(stdout, result)
            return result

        if self.project == "oniguruma":
            # The trailing log section repeats test names; ignore it.
            stdout = stdout.split("Testsuite summary")[0]

        if self.project not in unittest_patterns:
            raise ParseError(f"no unittest pattern for {self.project}")

        self._parse_by_pattern(stdout, result)
        return result

    def _parse_by_pattern(self, stdout: str, result: dict[str, Any]) -> None:
        patterns = unittest_patterns[self.project]
        if not isinstance(patterns, list):
            patterns = [patterns]

        for pattern in patterns:
            for test in re.finditer(pattern, stdout):
                groups = test.re.groupindex.keys()

                if "total" in groups and test.group("total") is not None:
                    if result["total"] is None:
                        result["total"] = 0
                    total = test.group("total")
                    result["total"] += int(total) if total.isdigit() else 1

                if "name" in groups and test.group("name") is not None:
                    status = self._normalise(test, groups)
                    for bucket in ("pass", "fail", "skip"):
                        if bucket in status and test.group("name") not in result[bucket]:
                            result[bucket].append(test.group("name"))

        if result["total"] is None:
            result["total"] = sum(len(result[b]) for b in ("pass", "fail", "skip"))

    @classmethod
    def _normalise(cls, test: re.Match, groups) -> str:
        """Map a project's status word onto pass/fail/skip. No status means pass."""
        if "status" not in groups or test.group("status") is None:
            return "pass"
        status = test.group("status").lower().strip()
        if status in cls._PASS_WORDS:
            return "pass"
        if status in cls._FAIL_WORDS:
            return "fail"
        if status in cls._SKIP_WORDS:
            return "skip"
        return status

    @staticmethod
    def _parse_libxml2(stdout, result):
        # libxml2 is weird, doesn't contain a status for passing tests.
        # Failure is indicated by a list of failing tests after a "## {NAME}" line.
        # Technically, the "## {NAME}" is the name of a group of unit tests
        # but we treat NAME as a single unit test since it doesn't list the
        # component unit tests that pass.
        # The failure line after "## {NAME}" is something like:
        # ./test/valid/781333.xml:4: element a: validity error
        # A passing test should just list the next "## {NAME}" line or state the
        # total, like "Total 9 tests, no errors"
        re_all = r'^## (?P<name>.*)$'
        re_failing = r'^## (?P<name>.*)\n.*error : '  # fail

        all_tests = set()
        all_matches = re.finditer(re_all, stdout, re.MULTILINE)
        for match in all_matches:
            all_tests.add(match.group("name"))

        failing_tests = set()
        failing_matches = re.finditer(re_failing, stdout, re.MULTILINE)
        for match in failing_matches:
            failing_tests.add(match.group("name"))

        passing_tests = all_tests - failing_tests

        result["pass"] = list(passing_tests)
        result["fail"] = list(failing_tests)
        result["total"] = len(all_tests)


    @staticmethod
    def _parse_htslib(stdout, result):
        result["total"] = 0
        pattern = unittest_patterns['htslib']
        for match in re.finditer(pattern, stdout):
            name = match.group("name")
            num_unexpected_failures = match.group("num_unexpected_failures")
            if num_unexpected_failures == '0':
                result["pass"].append(name)
            else:
                result["fail"].append(name)
            result["total"] += 1
        return result


    @staticmethod
    def _parse_ffmpeg(stdout, result):
        # ffmpeg is weird, doesn't contain a status for passing tests.
        # Failure is indicated by a "Test {test_name} failed." statement.
        # A passing test should just list the "TEST    {test_name}".
        re_all = r'^TEST\s+(?P<name>.*)$'
        re_failing = r'^Test (?P<name>.+) failed.'  # fail

        all_tests = set()
        all_matches = re.finditer(re_all, stdout, re.MULTILINE)
        for match in all_matches:
            all_tests.add(match.group("name"))

        failing_tests = set()
        failing_matches = re.finditer(re_failing, stdout, re.MULTILINE)
        for match in failing_matches:
            failing_tests.add(match.group("name"))

        passing_tests = all_tests - failing_tests

        result["pass"] = list(passing_tests)
        result["fail"] = list(failing_tests)
        result["total"] = len(all_tests)


    @staticmethod
    def _parse_libredwg(stdout, result):
        lines = stdout.strip().split('\n')

        # Extract test names from compilation phase
        test_names = set()

        # Look for CCLD lines which show the final executables being created
        showing_test_names = False
        for line in lines:
            line = line.strip()
            if '/src/libredwg/test/unit-testing' in line:
                showing_test_names = True
            if showing_test_names and line.startswith("CCLD "):
                # Extract the executable name after "CCLD "
                test_name = line[5:].strip()
                test_names.add(test_name)
            if line == "/src/libredwg":
                break

        # handles cases where test name is end of another test name
        test_names = list(test_names)
        test_names.sort(key=len)

        # Now parse the execution results
        passing_tests = set()
        failing_tests = set()
        current_test = None
        in_execution_phase = False

        for line in lines:
            line = line.strip()

            if line == "/src/libredwg":
                in_execution_phase = True
                continue

            if in_execution_phase:
                # Look for test names that we know exist from compilation
                for test_name in test_names:
                    if line == test_name or line.endswith(test_name):
                        # new test, so current test is passing if not in failing
                        if current_test and current_test not in failing_tests:
                            passing_tests.add(current_test)
                        current_test = test_name

                # Process TAP results
                # passes unless a 'not ok' line is under it
                if line.startswith("not ok ") and current_test:
                    failing_tests.add(current_test)

        # put last test in passing if its not in failing
        if current_test and current_test not in failing_tests:
            passing_tests.add(current_test)

        # put others in skip
        for test_name in test_names:
            if test_name not in passing_tests and test_name not in failing_tests:
                result['skip'].append(test_name)

        result["pass"] = list(passing_tests)
        result["fail"] = list(failing_tests)
        result["total"] = len(test_names)


    @staticmethod
    def _parse_wasm3(stdout, result):
        def parse_test_status(section_content: str) -> str:
            """
            Parse a test section and determine if the test passed or failed.

            Args:
                section_content (str): Content of a single test section

            Returns:
                str: 'pass' if test passed, 'fail' otherwise
            """
            # Look for the results dictionary pattern
            # This regex captures the test results in a more flexible way
            results_pattern = r"'crashed':\s*(\d+),\s*'failed':\s*(\d+),\s*'missing':\s*(\d+),\s*'skipped':\s*(\d+),\s*'success':\s*(\d+),\s*'timeout':\s*(\d+),\s*'total_run':\s*(\d+)"

            match = re.search(results_pattern, section_content)

            if not match:
                # If we can't find the results pattern, check for "Error: No tests run"
                if "Error: No tests run" in section_content:
                    return 'fail'
                # Default to fail if we can't parse the results
                return 'fail'

            crashed, failed, missing, skipped, success, timeout, total_run = map(
                int, match.groups())

            # Test passes if:
            # - No crashed, failed, missing, skipped, or timeout tests
            # - Positive number of successful tests
            # - Success count equals total_run count
            if (crashed == 0 and failed == 0 and missing == 0 and
                skipped == 0 and timeout == 0 and success > 0 and
                    success == total_run):
                return 'pass'
            else:
                return 'fail'

        # Split content into sections based on the separator pattern
        sections = re.split(r'=+ Running .+ =+', stdout)

        # Find all test names using the regex pattern
        test_names = re.findall(r'=+ Running (?P<name>\S+) =+', stdout)

        # Process each section (skip the first empty section)
        for i, section in enumerate(sections[1:], 0):
            if i >= len(test_names):
                break

            test_name = test_names[i]
            status = parse_test_status(section)

            if status == 'pass':
                result['pass'].append(test_name)
            elif status == 'fail':
                result['fail'].append(test_name)

        result['total'] = len(test_names)

    #: Projects whose output needs more than a regex sweep.
    _SPECIAL_CASES: dict[str, Callable[[str, dict], Any]] = {
        "libxml2": _parse_libxml2,
        "htslib": _parse_htslib,
        "ffmpeg": _parse_ffmpeg,
        "libredwg": _parse_libredwg,
        "wasm3": _parse_wasm3,
    }
