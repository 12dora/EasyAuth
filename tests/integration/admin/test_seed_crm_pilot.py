from __future__ import annotations

from http import HTTPStatus
from io import StringIO
from re import search
from typing import Final

import pytest
from django.core.management import call_command
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppCredential,
    ApprovalRule,
    Permission,
    Role,
    RolePermission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantRole

pytestmark = pytest.mark.django_db

EXPECTED_ROLE_COUNT: Final = 2
EXPECTED_PERMISSION_COUNT: Final = 3
EXPECTED_ROLE_PERMISSION_COUNT: Final = 3
EXPECTED_APPROVAL_RULE_COUNT: Final = 2


def test_seed_crm_pilot_creates_idempotent_configuration_and_one_time_token() -> None:
    # Given
    first_stdout = StringIO()

    # When
    _ = call_command("seed_crm_pilot", stdout=first_stdout)

    # Then
    first_output = first_stdout.getvalue()
    token_match = search(r"eat_[A-Za-z0-9_-]+", first_output)
    assert token_match is not None
    plaintext_token = token_match.group(0)
    app = App.objects.get(app_key="crm")
    assert Role.objects.filter(app=app, key="admin", requestable=True).exists()
    assert Role.objects.filter(app=app, key="auditor", requestable=True).exists()
    assert Permission.objects.filter(app=app, key="customer:view:department").exists()
    assert Permission.objects.filter(app=app, key="customer:export").exists()
    assert RolePermission.objects.filter(role__app=app).count() == EXPECTED_ROLE_PERMISSION_COUNT
    assert ApprovalRule.objects.filter(app=app, role__key="admin", is_active=True).exists()
    assert AppCredential.objects.filter(app=app, credential_type="static_token").count() == 1
    assert plaintext_token not in str(AppCredential.objects.values_list("token_hash", flat=True))
    assert plaintext_token not in str(AuditLog.objects.values_list("metadata", flat=True))

    # When: 种子命令重复运行。
    second_stdout = StringIO()
    _ = call_command("seed_crm_pilot", stdout=second_stdout)

    # Then: 不重复创建试点配置, 也不重新泄露不可恢复的明文 token。
    assert App.objects.filter(app_key="crm").count() == 1
    assert Role.objects.filter(app=app).count() == EXPECTED_ROLE_COUNT
    assert Permission.objects.filter(app=app).count() == EXPECTED_PERMISSION_COUNT
    assert RolePermission.objects.filter(role__app=app).count() == EXPECTED_ROLE_PERMISSION_COUNT
    assert ApprovalRule.objects.filter(app=app).count() == EXPECTED_APPROVAL_RULE_COUNT
    assert AppCredential.objects.filter(app=app, credential_type="static_token").count() == 1
    assert search(r"eat_[A-Za-z0-9_-]+", second_stdout.getvalue()) is None


def test_seed_crm_pilot_token_can_query_seeded_grant_through_api() -> None:
    # Given
    stdout = StringIO()
    _ = call_command("seed_crm_pilot", stdout=stdout)
    token_match = search(r"eat_[A-Za-z0-9_-]+", stdout.getvalue())
    assert token_match is not None
    user = UserMirror.objects.get(authentik_user_id="crm-pilot-user")
    app = App.objects.get(app_key="crm")
    grant = AccessGrant.objects.get(user=user, app=app, is_current=True)
    assert AccessGrantRole.objects.filter(grant=grant, role__key="admin").exists()

    # When
    response = Client().get(
        f"/api/v1/apps/{app.app_key}/users/{user.authentik_user_id}/permissions",
        HTTP_AUTHORIZATION=f"Bearer {token_match.group(0)}",
    )

    # Then
    assert response.status_code == HTTPStatus.OK
    assert b'"roles": ["admin"]' in response.content
    assert (
        b'"permissions": ["customer:export", "customer:view:department"]'
        in response.content
    )
