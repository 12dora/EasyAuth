"""HandoverActionSkipRecord 豁免 retention(01 §2.2.1)。"""

from __future__ import annotations

import inspect

import pytest

from easyauth.config import data_retention
from easyauth.lifecycle.models import HandoverActionSkipRecord

pytestmark = pytest.mark.django_db


def test_skip_record_excluded_from_retention_cleanup() -> None:
    source = inspect.getsource(data_retention.run_retention_cleanup)
    assert "HandoverActionSkipRecord" not in source
    assert "handoveractionskiprecord" not in source.lower()
    # 表存在且不被任何 prune 辅助函数引用
    prune_sources = "\n".join(
        inspect.getsource(fn)
        for name, fn in vars(data_retention).items()
        if callable(fn) and name.startswith(("prune_", "minimize_", "run_"))
    )
    assert "HandoverActionSkipRecord" not in prune_sources
    assert HandoverActionSkipRecord._meta.db_table  # noqa: SLF001
