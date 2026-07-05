from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.models.expressions import Expression

    _CharFieldBase = models.CharField[str, str]
else:
    _CharFieldBase = models.CharField

FIELD_ENCRYPTION_KEY_MISSING = (
    "EASYAUTH_FIELD_ENCRYPTION_KEY 未配置, 无法加密敏感字段。"
)
FIELD_DECRYPTION_FAILED = (
    "敏感字段解密失败: 密文与当前 EASYAUTH_FIELD_ENCRYPTION_KEY 不匹配。"
)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    # 从专用配置项派生 Fernet 密钥; 库泄露(不含应用密钥)无法解密。
    raw_key = str(getattr(settings, "EASYAUTH_FIELD_ENCRYPTION_KEY", "")).strip()
    if not raw_key:
        raise ImproperlyConfigured(FIELD_ENCRYPTION_KEY_MISSING)
    derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt_value(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        # 解密失败必须快速失败: 静默返回空会让目录同步/二次验证在无凭据下"看似正常"。
        raise ImproperlyConfigured(FIELD_DECRYPTION_FAILED) from error


class EncryptedCharField(_CharFieldBase):
    # 静态加密的字符串字段: Python 层始终是明文, 数据库列里是 Fernet 密文。
    # max_length 必须能容纳密文(约为明文长度 + ~120 字符的 base64 开销)。

    def from_db_value(
        self,
        value: str | None,
        expression: Expression,
        connection: BaseDatabaseWrapper,
    ) -> str | None:
        _ = (expression, connection)
        if value is None or value == "":
            return value
        return decrypt_value(value)

    def get_prep_value(self, value: object) -> str | None:
        prepared = super().get_prep_value(value)
        if prepared is None or prepared == "":
            return prepared
        return encrypt_value(prepared)
