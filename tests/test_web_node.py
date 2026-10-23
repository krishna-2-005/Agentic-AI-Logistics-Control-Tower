"""
Runs the site's pure-function Node tests (`web/tests/web_format.test.mjs`) from pytest.

The formatting, corridor filtering, paging and glossary logic is written as plain
TypeScript with no framework imports, so Node can execute it directly. The test is
skipped when Node is not installed or is too old to strip types.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from src.common import config

TEST_FILE = config.REPO_ROOT / "web" / "tests" / "web_format.test.mjs"


def _node_major() -> int | None:
    node = shutil.which("node")
    if node is None:
        return None
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    try:
        return int(out.stdout.strip().lstrip("v").split(".")[0])
    except ValueError:
        return None


@pytest.mark.skipif(
    (_node_major() or 0) < 22, reason="Node 22.18+ is needed to run TypeScript directly"
)
def test_site_formatting_filtering_and_glossary_in_node() -> None:
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--test", str(TEST_FILE)],
        capture_output=True,
        text=True,
        cwd=config.REPO_ROOT / "web",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
