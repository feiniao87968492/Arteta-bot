import json
import os
import subprocess
import sys
import time
from typing import Dict, Generator, List, Optional


ALLOWED_SUITES = set(["core", "render", "memory", "chat", "commands", "online", "all"])


class VerifyService:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.script_path = os.path.join(repo_root, "tools", "verify_features.py")
        self.runs = {}  # type: Dict[str, Dict[str, object]]

    def build_args(self, suites: List[str], cases: List[str], online: bool, allow_side_effects: bool) -> List[str]:
        args = []  # type: List[str]
        for suite in suites or ["core"]:
            if suite not in ALLOWED_SUITES:
                raise ValueError("unknown suite: " + suite)
            args.extend(["--suite", suite])
        for case in cases:
            args.extend(["--case", case])
        if online:
            args.append("--online")
        if allow_side_effects:
            args.append("--allow-side-effects")
        return args

    def start_run(self, suites: List[str], cases: List[str], online: bool, allow_side_effects: bool) -> str:
        run_id = str(int(time.time() * 1000))
        args = [sys.executable, self.script_path] + self.build_args(suites, cases, online, allow_side_effects)
        process = subprocess.Popen(
            args,
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            universal_newlines=True,
        )
        self.runs[run_id] = {"process": process, "args": args}
        return run_id

    def stream_lines(self, run_id: str) -> Generator[str, None, None]:
        if run_id not in self.runs:
            raise KeyError("unknown verification run: " + run_id)
        process = self.runs[run_id]["process"]
        assert isinstance(process, subprocess.Popen)
        assert process.stdout is not None
        for line in process.stdout:
            yield line.rstrip("\n")
        process.wait()
        yield "[dashboard] verification exited with code {}".format(process.returncode)

    def latest_report(self) -> Optional[Dict[str, object]]:
        verify_root = os.path.join(self.repo_root, "artifacts", "verify")
        if not os.path.isdir(verify_root):
            return None
        runs = sorted(os.listdir(verify_root), reverse=True)
        for run in runs:
            report = os.path.join(verify_root, run, "report.json")
            if os.path.isfile(report):
                with open(report, "r", encoding="utf-8") as f:
                    return json.load(f)
        return None
