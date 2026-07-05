from __future__ import annotations

import pyotp
import pytest
from django.db import connection

from easyauth.accounts.models import LocalAdminAccount

pytestmark = pytest.mark.django_db


def test_totp_secret_is_encrypted_at_rest_and_verifies() -> None:
    # Given: 一个绑定了 TOTP 种子的本地管理员。
    secret = pyotp.random_base32()
    account = LocalAdminAccount(username="totp-admin", totp_secret=secret, totp_enabled=True)
    account.set_password("Sup3rSecret-passphrase")
    account.save()

    # Then: 数据库列里是密文, 而 ORM 读取透明解密回明文。
    table = LocalAdminAccount._meta.db_table  # noqa: SLF001 - 读取列名.
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT totp_secret FROM {table} WHERE id = %s", [account.id])  # noqa: S608
        stored = cursor.fetchone()[0]
    assert stored != secret
    assert secret not in stored

    reloaded = LocalAdminAccount.objects.get(id=account.id)
    assert reloaded.totp_secret == secret
    # 还原后的种子仍能校验对应的 TOTP 验证码。
    assert pyotp.TOTP(reloaded.totp_secret).verify(pyotp.TOTP(secret).now()) is True
