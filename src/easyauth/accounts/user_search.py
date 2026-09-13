"""用户模糊检索: 姓名/拼音/用户 ID/邮箱/工号。

控制台人员选项与授权明细 `user_query` 共用同一套匹配, 不得各写一份 icontains。
"""

from __future__ import annotations

from django.db.models import Model, Q, QuerySet

from easyauth.accounts.pinyin import pinyin_query_filter

__all__ = ["apply_user_search", "user_search_q"]


def user_search_q(query: str, *, prefix: str = "") -> Q:
    """大小写不敏感子串匹配姓名、邮箱、Authentik 用户 ID、工号; 纯字母数字另匹配拼音。

    `prefix` 用于关联查询, 例如 `user__` 生成 `user__name__icontains`。
    """
    filters = (
        Q(**{f"{prefix}name__icontains": query})
        | Q(**{f"{prefix}email__icontains": query})
        | Q(**{f"{prefix}authentik_user_id__icontains": query})
        | Q(**{f"{prefix}employee_number__icontains": query})
    )
    pinyin_filter = pinyin_query_filter(query, prefix=prefix)
    if pinyin_filter is not None:
        filters |= pinyin_filter
    return filters


def apply_user_search[T: Model](
    queryset: QuerySet[T],
    query: str,
    *,
    prefix: str = "",
) -> QuerySet[T]:
    return queryset.filter(user_search_q(query, prefix=prefix))
