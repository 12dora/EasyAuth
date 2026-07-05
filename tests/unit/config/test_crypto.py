from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from easyauth.config import crypto


@pytest.fixture(autouse=True)
def _reset_fernet_cache() -> None:
    # _fernet 使用 lru_cache; 每个用例前后清空, 避免密钥覆盖泄漏到其他用例。
    crypto._fernet.cache_clear()  # noqa: SLF001 - 测试直接控制缓存.
    yield
    crypto._fernet.cache_clear()  # noqa: SLF001 - 测试直接控制缓存.


def test_encrypt_decrypt_round_trip() -> None:
    ciphertext = crypto.encrypt_value("s3cr3t-token")
    # 密文与明文不同, 且能还原。
    assert ciphertext != "s3cr3t-token"
    assert crypto.decrypt_value(ciphertext) == "s3cr3t-token"


def test_decrypt_rejects_tampered_ciphertext() -> None:
    with pytest.raises(ImproperlyConfigured):
        _ = crypto.decrypt_value("not-a-valid-fernet-token")


@override_settings(EASYAUTH_FIELD_ENCRYPTION_KEY="")
def test_missing_key_fails_fast() -> None:
    crypto._fernet.cache_clear()  # noqa: SLF001 - 强制在空密钥下重新构造.
    with pytest.raises(ImproperlyConfigured):
        _ = crypto.encrypt_value("anything")


def test_wrong_key_cannot_decrypt() -> None:
    with override_settings(EASYAUTH_FIELD_ENCRYPTION_KEY="key-one"):
        crypto._fernet.cache_clear()  # noqa: SLF001 - 使用第一把密钥加密.
        ciphertext = crypto.encrypt_value("payload")
    with override_settings(EASYAUTH_FIELD_ENCRYPTION_KEY="key-two"):
        crypto._fernet.cache_clear()  # noqa: SLF001 - 换密钥后应无法解密.
        with pytest.raises(ImproperlyConfigured):
            _ = crypto.decrypt_value(ciphertext)
