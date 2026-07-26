#!/usr/bin/env python
from __future__ import annotations

import os
import sys
from pathlib import Path

from django.core.management import execute_from_command_line

from easyauth.config.local_env import load_local_env


def main() -> None:
    load_local_env(Path(__file__).resolve().parent / ".env.local")
    _ = os.environ.setdefault("DJANGO_SETTINGS_MODULE", "easyauth.config.settings.base")
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
