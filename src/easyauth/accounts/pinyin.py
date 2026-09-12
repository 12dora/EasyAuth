from __future__ import annotations

from django.db.models import Q
from pypinyin import Style, lazy_pinyin

__all__ = ["name_pinyin_fields", "pinyin_query_filter"]


def name_pinyin_fields(name: str) -> tuple[str, str]:
    """把姓名转成全拼与首字母, 供选人搜索。

    汉字按拼音音节展开; 非 CJK 的 ASCII 字母/数字原样保留(小写)。
    例: 胡玉琴A → ("huyuqina", "hyqa")。
    """
    full: list[str] = []
    initials: list[str] = []
    for char in name:
        if char.isascii() and char.isalnum():
            lowered = char.lower()
            full.append(lowered)
            initials.append(lowered)
            continue
        for syllable in lazy_pinyin(char, style=Style.NORMAL):
            letters = "".join(ch.lower() for ch in syllable if ch.isascii() and ch.isalnum())
            if not letters:
                continue
            full.append(letters)
            initials.append(letters[0])
    return "".join(full), "".join(initials)


def pinyin_query_filter(q: str) -> Q | None:
    """纯字母数字查询时匹配姓名全拼/首字母; 否则返回 None。"""
    pinyin_query = q.lower().replace(" ", "")
    if pinyin_query.isascii() and pinyin_query.isalnum():
        return Q(name_pinyin__icontains=pinyin_query) | Q(
            name_pinyin_initials__icontains=pinyin_query,
        )
    return None
