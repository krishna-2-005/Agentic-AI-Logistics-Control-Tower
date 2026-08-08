"""Versioned prompt library.

GIT_RULES §1: prompts are versioned (v1, v2 …) and **never overwritten**. Week 4's
commit message ``invoice_no accuracy 0.71 -> 0.93`` only means something if the v1
that scored 0.71 still exists to compare against.

Layout::

    src/agents/prompts/
    ├── registry.py                 # this file
    ├── doc_extraction/
    │   ├── v1.md
    │   └── v2.md                   # v1 stays. Always.
    ├── order_entry/
    ├── exception_triage/
    ├── invoice_audit/
    └── analytics_assistant/

Usage::

    from src.agents.prompts.registry import load_prompt

    prompt = load_prompt("doc_extraction")            # newest version
    prompt = load_prompt("doc_extraction", "v1")      # pinned, for an ablation
    text = prompt.render(document_text=ocr_output)

Evaluation runs pin an explicit version so a result is always reproducible; the
version used is recorded alongside every score in ``benchmarks/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent

VERSION_RE = re.compile(r"^v(\d+)$")


@dataclass(frozen=True)
class Prompt:
    """A loaded prompt template."""

    agent: str
    version: str
    text: str
    path: Path

    def render(self, **values: object) -> str:
        """Substitute ``${placeholders}``, raising if any are missing.

        ``Template.substitute`` rather than ``str.format`` because prompts are full of
        literal JSON braces, and a silently unsubstituted placeholder reaching the
        model is a bug that shows up as a mysterious accuracy drop three days later.
        """
        return Template(self.text).substitute(**values)

    @property
    def label(self) -> str:
        """What gets written into the benchmark row, e.g. ``doc_extraction/v2``."""
        return f"{self.agent}/{self.version}"


def _agent_dir(agent: str) -> Path:
    path = PROMPTS_DIR / agent
    if not path.is_dir():
        available = sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))
        raise FileNotFoundError(f"No prompt directory for agent {agent!r}. Available: {available}")
    return path


def list_versions(agent: str) -> list[str]:
    """All versions for an agent, oldest first."""
    versions = []
    for file in _agent_dir(agent).glob("v*.md"):
        m = VERSION_RE.match(file.stem)
        if m:
            versions.append((int(m.group(1)), file.stem))
    return [name for _, name in sorted(versions)]


def load_prompt(agent: str, version: str | None = None) -> Prompt:
    """Load a prompt. ``version=None`` takes the highest-numbered version."""
    versions = list_versions(agent)
    if not versions:
        raise FileNotFoundError(f"No vN.md prompt files in {_agent_dir(agent)}")

    version = version or versions[-1]
    if version not in versions:
        raise FileNotFoundError(
            f"Prompt {agent}/{version} not found. Available: {versions}"
        )

    path = _agent_dir(agent) / f"{version}.md"
    return Prompt(agent=agent, version=version, text=path.read_text(encoding="utf-8"), path=path)


def inventory() -> dict[str, list[str]]:
    """Every agent and its versions — rendered on the dashboard's prompt page."""
    return {
        d.name: list_versions(d.name)
        for d in sorted(PROMPTS_DIR.iterdir())
        if d.is_dir() and not d.name.startswith(("_", "."))
    }
