from __future__ import annotations

import re
from pathlib import Path

from .config import PROJECT_ROOT
from .models import RunCardActor, RunCardTriggerSource, RunCardType, SkillValidationIssue, SkillValidationReport
from .run_cards import RunCardService
from .store import Store


FORBIDDEN_SKILL_PHRASES = {
    "unlock_trade",
    "place live order",
    "approve live",
    "bypass policy",
    "direct execution",
}
SKILL_VALIDATION_RULE_VERSION = "skill_validator_v1"


class SkillValidatorService:
    def __init__(self, store: Store, root: Path | None = None):
        self.store = store
        self.root = root or PROJECT_ROOT

    def validate(self, *, actor: RunCardActor | str = RunCardActor.CLI) -> SkillValidationReport:
        skill_paths = sorted((self.root / "skills").glob("*/SKILL.md")) if (self.root / "skills").exists() else []
        command_paths = sorted((self.root / "commands").glob("*.md")) if (self.root / "commands").exists() else []
        tool_names = _mcp_tool_names()
        issues: list[SkillValidationIssue] = []
        for path in [*skill_paths, *command_paths]:
            text = path.read_text(encoding="utf-8")
            if path.name == "SKILL.md":
                if not re.search(r"^name\s*:", text, flags=re.MULTILINE | re.IGNORECASE):
                    issues.append(SkillValidationIssue(path=str(path), message="missing name field"))
                if not re.search(r"^description\s*:", text, flags=re.MULTILINE | re.IGNORECASE):
                    issues.append(SkillValidationIssue(path=str(path), message="missing description field"))
                if not re.search(r"^allowed_tools\s*:", text, flags=re.MULTILINE | re.IGNORECASE):
                    issues.append(SkillValidationIssue(path=str(path), message="missing allowed_tools field"))
            lowered = text.lower()
            for phrase in FORBIDDEN_SKILL_PHRASES:
                if phrase in lowered:
                    issues.append(SkillValidationIssue(path=str(path), message=f"forbidden execution phrase: {phrase}"))
            for tool in _declared_tools(text):
                if tool not in tool_names:
                    issues.append(SkillValidationIssue(path=str(path), message=f"unknown MCP tool: {tool}"))
            if "create_trade_proposal" in text and "evidence gate" not in lowered:
                issues.append(SkillValidationIssue(path=str(path), message="proposal tool reference must warn about evidence gate"))
        run_card = RunCardService(self.store).start_run(
            RunCardType.SKILL_VALIDATION,
            title="Local Skill Manifest Validation",
            actor=actor,
            trigger_source=RunCardTriggerSource.MANUAL,
            rule_version=SKILL_VALIDATION_RULE_VERSION,
            inputs={"root": str(self.root)},
            dataset={"skill_count": len(skill_paths), "command_count": len(command_paths)},
            assumptions={"skills_are_documentation_only": True, "skills_do_not_grant_permissions": True},
        )
        report = SkillValidationReport(
            checked_count=len(skill_paths) + len(command_paths),
            issue_count=len(issues),
            issues=issues,
            summary="skill validation passed" if not issues else f"skill validation found {len(issues)} issue(s)",
            run_card_id=run_card.id,
        )
        RunCardService(self.store).complete_run(
            run_card.id,
            metrics={"checked_count": report.checked_count, "issue_count": report.issue_count},
            warnings=[issue.message for issue in issues],
            outputs=report.model_dump(mode="json"),
            dataset={"issues": [issue.model_dump(mode="json") for issue in issues]},
        )
        return report


def _declared_tools(text: str) -> list[str]:
    result: list[str] = []
    in_tools = False
    for line in text.splitlines():
        if re.match(r"^allowed_tools\s*:", line, flags=re.IGNORECASE):
            in_tools = True
            continue
        if in_tools and line and not line.startswith((" ", "-", "\t")):
            break
        match = re.match(r"\s*-\s*([a-zA-Z_][a-zA-Z0-9_]*)", line)
        if in_tools and match:
            result.append(match.group(1))
    return result


def _mcp_tool_names() -> set[str]:
    import invest_agent.mcp_server as mcp_server

    return {
        name
        for name, value in vars(mcp_server).items()
        if callable(value) and not name.startswith("_") and name not in {"main"}
    }

