from __future__ import annotations

import os
from pathlib import Path
from typing import Final

MIN_QUOTED_ENV_VALUE_LENGTH: Final = 2
REPO_ROOT: Final = Path(__file__).resolve().parents[3]


def load_local_env(env_path: Path | None = None) -> None:
    """加载仓库根目录的 .env.local; 与 manage.py 行为一致, 不覆盖已有环境变量。

    生产部署不携带 .env.local, 缺失关键配置时由 settings 的 fail-fast 校验直接拒绝启动,
    不会再静默回退到 SQLite 或开发密钥。
    """
    path = env_path if env_path is not None else REPO_ROOT / ".env.local"
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "" or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        if key == "" or key in os.environ:
            continue

        os.environ[key] = _unquote_env_value(value.strip())


def _unquote_env_value(value: str) -> str:
    if (
        len(value) >= MIN_QUOTED_ENV_VALUE_LENGTH
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        return value[1:-1]
    return value
