from __future__ import annotations

import pytest

from easyauth.api.pagination import total_pages


def test_total_pages_computes_ceiling() -> None:
    assert total_pages(total_items=0, page_size=20) == 0
    assert total_pages(total_items=1, page_size=20) == 1
    assert total_pages(total_items=20, page_size=20) == 1
    two_pages = 2
    assert total_pages(total_items=21, page_size=20) == two_pages


@pytest.mark.parametrize("page_size", [0, -1])
def test_total_pages_rejects_non_positive_page_size(page_size: int) -> None:
    # 非正 page_size 是不可能状态: 快速失败, 不静默返回 0。
    with pytest.raises(ValueError, match="page_size"):
        _ = total_pages(total_items=10, page_size=page_size)
