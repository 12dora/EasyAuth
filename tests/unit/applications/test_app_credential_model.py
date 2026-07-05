from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from easyauth.applications.models import (
    APP_CREDENTIAL_STATIC_KIND,
    App,
    AppCredential,
)

pytestmark = pytest.mark.django_db


def test_static_credential_clean_rejects_empty_token_lookup() -> None:
    # Given: 一个 token_lookup 为空的 active 静态凭据(不可认证的垃圾状态)。
    app = App.objects.create(app_key="cred-clean-app", name="Cred Clean")
    credential = AppCredential(
        app=app,
        credential_type=APP_CREDENTIAL_STATIC_KIND,
        name="broken",
        token_hash="x" * 32,
        token_lookup="",
    )

    # When / Then: clean 快速失败, 不允许落库。
    with pytest.raises(ValidationError) as error:
        credential.full_clean()
    assert "token_lookup" in error.value.message_dict


def test_static_credential_clean_accepts_populated_token_lookup() -> None:
    app = App.objects.create(app_key="cred-ok-app", name="Cred OK")
    credential = AppCredential(
        app=app,
        credential_type=APP_CREDENTIAL_STATIC_KIND,
        name="valid",
        token_hash="x" * 32,
        token_lookup="a" * 64,
    )

    # 非空 token_lookup 通过校验。
    credential.full_clean()
