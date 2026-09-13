from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GIT_MISSING_MESSAGE = "git executable is required to list tracked src files"


def head_src_python_texts() -> list[tuple[str, str]]:
    """Return (repo-relative path, HEAD blob) for tracked src Python files."""
    git = _git_executable()
    listed = subprocess.run(
        [git, "ls-tree", "-r", "--name-only", "-z", "HEAD", "src"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    relatives: list[str] = []
    for raw in listed.stdout.split(b"\0"):
        if raw == b"":
            continue
        relative = Path(raw.decode())
        if relative.suffix != ".py" or "migrations" in relative.parts:
            continue
        relatives.append(relative.as_posix())
    if not relatives:
        return []
    query = "".join(f"HEAD:{path}\n" for path in relatives).encode()
    blob = subprocess.run(
        [git, "cat-file", "--batch"],
        cwd=REPO_ROOT,
        check=True,
        input=query,
        capture_output=True,
    )
    return list(zip(relatives, _parse_cat_file_batch(blob.stdout), strict=True))


def _parse_cat_file_batch(payload: bytes) -> list[str]:
    texts: list[str] = []
    cursor = 0
    while cursor < len(payload):
        newline = payload.find(b"\n", cursor)
        header = payload[cursor:newline].decode()
        _sha, kind, size_text = header.split(" ")
        if kind != "blob":
            missing = f"unexpected git cat-file kind {kind}"
            raise RuntimeError(missing)
        size = int(size_text)
        start = newline + 1
        end = start + size
        texts.append(payload[start:end].decode())
        cursor = end + 1
    return texts


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError(GIT_MISSING_MESSAGE)
    return git
