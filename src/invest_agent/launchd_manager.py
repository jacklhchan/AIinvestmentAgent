from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT


DAILY_POST_CLOSE_LABEL = "com.local.invest-agent-daily-post-close"
DAILY_POST_CLOSE_PLIST = PROJECT_ROOT / "deploy" / "launchd" / f"{DAILY_POST_CLOSE_LABEL}.plist"


def install_daily_post_close_launchd() -> dict[str, Any]:
    target = _install_plist(DAILY_POST_CLOSE_PLIST, DAILY_POST_CLOSE_LABEL)
    _launchctl(["bootstrap", _gui_domain(), str(target)], tolerate_failure=True)
    return status_daily_post_close_launchd()


def repair_daily_post_close_launchd() -> dict[str, Any]:
    target = _install_plist(DAILY_POST_CLOSE_PLIST, DAILY_POST_CLOSE_LABEL)
    _launchctl(["bootout", _gui_domain(), str(target)], tolerate_failure=True)
    _launchctl(["bootstrap", _gui_domain(), str(target)], tolerate_failure=True)
    return status_daily_post_close_launchd()


def status_daily_post_close_launchd() -> dict[str, Any]:
    label = DAILY_POST_CLOSE_LABEL
    target = _launch_agents_dir() / f"{label}.plist"
    result = _launchctl(["print", f"{_gui_domain()}/{label}"], tolerate_failure=True)
    parsed = _parse_launchctl_print(result.stdout)
    return {
        "label": label,
        "source_plist": str(DAILY_POST_CLOSE_PLIST),
        "installed_plist": str(target),
        "installed": target.exists(),
        "loaded": result.returncode == 0,
        "running": parsed.get("pid") is not None,
        "pid": parsed.get("pid"),
        "last_exit_status": parsed.get("last_exit_status"),
        "returncode": result.returncode,
        "stderr": result.stderr.strip(),
    }


def _install_plist(source: Path, label: str) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"launchd plist not found: {source}")
    destination = _launch_agents_dir() / f"{label}.plist"
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8").replace("${INVEST_AGENT_REPO_ROOT}", str(PROJECT_ROOT))
    destination.write_text(text, encoding="utf-8")
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    return destination


def _launchctl(args: list[str], *, tolerate_failure: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["launchctl", *args], text=True, capture_output=True, check=False)
    if result.returncode and not tolerate_failure:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"launchctl {' '.join(args)} failed")
    return result


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _parse_launchctl_print(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("pid ="):
            try:
                parsed["pid"] = int(line.split("=", 1)[1].strip())
            except ValueError:
                pass
        if line.startswith("last exit code =") or line.startswith("last exit status ="):
            try:
                parsed["last_exit_status"] = int(line.split("=", 1)[1].strip())
            except ValueError:
                parsed["last_exit_status"] = line.split("=", 1)[1].strip()
    return parsed
