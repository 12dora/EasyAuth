from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.unit.config.src_head import REPO_ROOT, head_src_python_texts

if TYPE_CHECKING:
    from pathlib import Path

BASELINE_PATH = REPO_ROOT / "scripts" / "ruff-noqa-baseline.txt"
NOQA_CODES = re.compile(r"\b(C901|PLR09\d+)\b")
FUNCTION_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
NOQA_PREFIX = "# noqa:"


def test_production_complexity_noqa_set_matches_baseline() -> None:
    measured = _collect_complexity_noqa()
    baseline = _load_baseline(BASELINE_PATH)
    added = sorted(measured - baseline)
    stale = sorted(baseline - measured)
    assert added == [], f"新增 C901/PLR09xx noqa, 禁止扩表: {added}"
    assert stale == [], f"baseline 含已消失的 noqa, 请删行: {stale}"


def _collect_complexity_noqa() -> set[str]:
    found: set[str] = set()
    for relative, content in head_src_python_texts():
        for line_number, line in enumerate(content.splitlines(), start=1):
            marker_at = line.find(NOQA_PREFIX)
            if marker_at < 0:
                continue
            codes = NOQA_CODES.findall(line[marker_at:])
            if not codes:
                continue
            match = FUNCTION_DEF.search(line)
            name = match.group(1) if match is not None else f"L{line_number}"
            found.update(f"{relative}:{name}:{code}" for code in codes)
    return found


def _load_baseline(path: Path) -> set[str]:
    entries: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "" or line.startswith("#"):
            continue
        entries.add(line)
    return entries
