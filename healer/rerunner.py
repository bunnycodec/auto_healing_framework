from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RerunResult:
    passed: bool
    output: str
    exit_code: int


class TestRerunner:
    def rerun(self, *, project_root: Path, command: str) -> RerunResult:
        completed = subprocess.run(
            command,
            cwd=project_root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        return RerunResult(
            passed=completed.returncode == 0,
            output=output,
            exit_code=completed.returncode,
        )