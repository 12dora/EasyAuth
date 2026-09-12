from __future__ import annotations

from pypinyin import Style, lazy_pinyin

__all__ = ["name_pinyin_fields"]


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
