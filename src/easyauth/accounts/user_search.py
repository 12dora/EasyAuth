"""用户模糊检索: 姓名/拼音/用户 ID/邮箱/工号。

控制台人员选项与授权明细 `user_query` 共用同一套匹配, 不得各写一份 icontains。
通讯录未注册人员另用 `directory_user_search_q`: 姓名 icontains、工号 iexact、钉钉 user_id exact。
"""

from __future__ import annotations

from django.db.models import Model, Q, QuerySet

from easyauth.accounts.pinyin import pinyin_query_filter

__all__ = ["apply_user_search", "directory_user_search_q", "user_search_q"]


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


def directory_user_search_q(query: str) -> Q:
    """钉钉通讯录未注册人员匹配: 姓名子串、工号全等、钉钉 user_id 全等。

    DingTalkUserMirror 无拼音列, 不得用 UserMirror 的拼音/邮箱/Authentik ID 规则冒充。
    """
    return Q(name__icontains=query) | Q(employee_number__iexact=query) | Q(user_id=query)


def apply_user_search[T: Model](
    queryset: QuerySet[T],
    query: str,
    *,
    prefix: str = "",
) -> QuerySet[T]:
    return queryset.filter(user_search_q(query, prefix=prefix))
