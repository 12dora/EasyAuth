from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING

from tests.unit.config.src_head import head_src_python_texts

if TYPE_CHECKING:
    from collections.abc import Iterator

BASELINE_PATH = Path(__file__).resolve().parent / "code_quality_baseline.json"
FILE_LINE_CAP = 600
FUNCTION_SPAN_CAP = 60


def test_src_file_lengths_respect_cap_and_baseline() -> None:
    measured = {path: length for path, length in _iter_file_lengths() if length > FILE_LINE_CAP}
    _assert_ratchet(
        measured=measured,
        baseline=_load_baseline()["files"],
        cap=FILE_LINE_CAP,
        kind="file",
    )


def test_src_function_spans_respect_cap_and_baseline() -> None:
    measured = {key: span for key, span in _iter_function_spans() if span > FUNCTION_SPAN_CAP}
    _assert_ratchet(
        measured=measured,
        baseline=_load_baseline()["functions"],
        cap=FUNCTION_SPAN_CAP,
        kind="function",
    )


def _assert_ratchet(
    *,
    measured: dict[str, int],
    baseline: dict[str, int],
    cap: int,
    kind: str,
) -> None:
    added = sorted(key for key in measured if key not in baseline)
    stale = sorted(
        key for key, recorded in baseline.items() if key not in measured or measured[key] <= cap
    )
    grown = sorted(
        f"{key}: {measured[key]} > {baseline[key]}"
        for key in measured
        if key in baseline and measured[key] > baseline[key]
    )
    assert added == [], f"新增超帽 {kind}, 禁止扩表: {added}"
    assert stale == [], f"{kind} baseline 含已还清或已消失条目, 请删行: {stale}"
    assert grown == [], f"{kind} 实测超过 baseline 记录值: {grown}"


def _iter_file_lengths() -> Iterator[tuple[str, int]]:
    for relative, content in head_src_python_texts():
        yield relative, len(content.splitlines())


def _iter_function_spans() -> Iterator[tuple[str, int]]:
    for relative, content in head_src_python_texts():
        tree = ast.parse(content, filename=relative)
        for qualname, span in _functions_in(tree):
            yield f"{relative}:{qualname}", span


def _functions_in(tree: ast.AST) -> Iterator[tuple[str, int]]:
    stack: list[str] = []

    def visit(node: ast.AST) -> Iterator[tuple[str, int]]:
        if isinstance(node, ast.ClassDef):
            stack.append(node.name)
            for child in ast.iter_child_nodes(node):
                yield from visit(child)
            stack.pop()
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield ".".join([*stack, node.name]), _span_including_decorators(node)
            stack.append(node.name)
            for child in ast.iter_child_nodes(node):
                yield from visit(child)
            stack.pop()
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    yield from visit(tree)


def _span_including_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    start = node.lineno
    if node.decorator_list:
        start = min(decorator.lineno for decorator in node.decorator_list)
    end = node.end_lineno if node.end_lineno is not None else node.lineno
    return end - start + 1


def _load_baseline() -> dict[str, dict[str, int]]:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    files = payload["files"]
    functions = payload["functions"]
    assert isinstance(files, dict)
    assert isinstance(functions, dict)
    return {"files": _int_map(files), "functions": _int_map(functions)}


def _int_map(raw: dict[object, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in raw.items():
        assert isinstance(key, str)
        assert isinstance(value, int)
        result[key] = value
    return result
