from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .store import Store


def _git_rev_parse(ref: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", ref],
            cwd=str(cwd or PROJECT_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


PROCESS_START_TIME = datetime.now(timezone.utc)
RUNNING_GIT_COMMIT = _git_rev_parse("HEAD")


class RuntimeVersionService:
    def __init__(self, store: Store, repo_root: Path | None = None):
        self.store = store
        self.repo_root = repo_root or PROJECT_ROOT

    def run(self) -> dict[str, Any]:
        current_head = _git_rev_parse("HEAD", cwd=self.repo_root)
        return {
            "running_git_commit": RUNNING_GIT_COMMIT,
            "current_git_head": current_head,
            "commit_mismatch": bool(
                RUNNING_GIT_COMMIT != "unknown" and current_head != "unknown" and RUNNING_GIT_COMMIT != current_head
            ),
            "process_start_time": PROCESS_START_TIME.isoformat(),
            "pid": os.getpid(),
            "repo_root": str(self.repo_root),
            "venv_python": sys.executable,
            "schema_table_count": self._schema_table_count(),
        }

    def _schema_table_count(self) -> int:
        with self.store.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone()["count"]
            )
