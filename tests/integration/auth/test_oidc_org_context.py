from __future__ import annotations

import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory

from easyauth.accounts.auth import VerifiedOidcClaims, bind_oidc_session
from easyauth.accounts.models import UserMirror

pytestmark = pytest.mark.django_db


def test_bind_oidc_session_updates_dingtalk_org_context() -> None:
    request = RequestFactory().get("/auth/callback/")
    SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
    request.session.save()
    claims = VerifiedOidcClaims(
        subject="ak-user",
        name="张三",
        email="zhangsan@example.test",
        groups=("EasyAuth Admins",),
        dingtalk_org={
            "name": "钉钉张三",
            "corp_id": "ding-corp",
            "user_id": "ding-user",
            "departments": [{"name": "销售部"}],
            "manager": {"user_id": "ding-manager", "name": "李经理"},
            "manager_chain": [{"user_id": "ding-manager", "name": "李经理"}],
            "mobile": "13800000000",
            "raw": {"secret": "ignored"},
            "stale": False,
            "last_synced_at": "2026-06-12T01:00:00+00:00",
        },
    )

    user = bind_oidc_session(request, claims)

    assert user.dingtalk_corp_id == "ding-corp"
    assert user.dingtalk_userid == "ding-user"
    assert user.name == "张三"
    assert user.department == "销售部"
    assert user.manager_userid == "ding-manager"
    assert request.session["easyauth_authentik_groups"] == ["EasyAuth Admins"]
    assert UserMirror.objects.get(authentik_user_id="ak-user").dingtalk_corp_id == "ding-corp"
