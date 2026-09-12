from __future__ import annotations

import re
from typing import Final

from django.db.models import Q
from pypinyin import Style, lazy_pinyin

__all__ = ["name_pinyin_fields", "pinyin_query_filter"]

_HAN_RUN: Final = re.compile(r"[一-鿿㐀-䶿]+")


def name_pinyin_fields(name: str) -> tuple[str, str]:
    """把姓名转成全拼与首字母, 供选人搜索。

    连续汉字按整段拼音展开(保留词组多音字); 其余片段只保留 ASCII 字母/数字并小写,
    整段同时写入全拼与首字母。
    例: 胡玉琴A → ("huyuqina", "hyqa"); Mike王 → ("mikewang", "mikew")。
    """
    full: list[str] = []
    initials: list[str] = []
    cursor = 0
    for match in _HAN_RUN.finditer(name):
        _append_literal_run(name[cursor : match.start()], full, initials)
        for syllable in lazy_pinyin(match.group(), style=Style.NORMAL):
            letters = _ascii_alnum(syllable)
            if not letters:
                continue
            full.append(letters)
            initials.append(letters[0])
        cursor = match.end()
    _append_literal_run(name[cursor:], full, initials)
    return "".join(full), "".join(initials)


def _append_literal_run(run: str, full: list[str], initials: list[str]) -> None:
    letters = _ascii_alnum(run)
    if not letters:
        return
    full.append(letters)
    initials.append(letters)


def _ascii_alnum(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isascii() and ch.isalnum())


def pinyin_query_filter(q: str) -> Q | None:
    """纯字母数字查询时匹配姓名全拼/首字母; 否则返回 None。"""
    pinyin_query = q.lower().replace(" ", "")
    if pinyin_query.isascii() and pinyin_query.isalnum():
        return Q(name_pinyin__icontains=pinyin_query) | Q(
            name_pinyin_initials__icontains=pinyin_query,
        )
    return None
