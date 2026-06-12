#!/usr/bin/env python
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

from django.core.management import execute_from_command_line

MIN_QUOTED_ENV_VALUE_LENGTH: Final = 2


def main() -> None:
    load_local_env(Path(__file__).resolve().parent / ".env.local")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "easyauth.config.settings.base")
    execute_from_command_line(sys.argv)


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
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


if __name__ == "__main__":
    main()
