from __future__ import annotations

import os
from pathlib import Path


HERMES_CONFIG_TEMPLATES = {
    "daily": "config.daily.snippet.yaml",
    "research-admin": "config.research-admin.snippet.yaml",
    "legacy": "config.snippet.yaml",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def render_hermes_config(*, kind: str = "daily", root: str | Path | None = None) -> str:
    template_name = HERMES_CONFIG_TEMPLATES.get(kind)
    if not template_name:
        raise ValueError(f"unknown Hermes config kind: {kind}")
    resolved_root = Path(root or os.environ.get("INVEST_AGENT_REPO_ROOT") or repo_root()).resolve()
    template = repo_root() / "deploy" / "hermes" / template_name
    return template.read_text(encoding="utf-8").replace("${INVEST_AGENT_REPO_ROOT}", str(resolved_root))


def write_hermes_config(*, kind: str = "daily", output_path: str | Path | None = None, root: str | Path | None = None) -> str:
    rendered = render_hermes_config(kind=kind, root=root)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    return rendered
