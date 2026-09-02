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
            "source_slug": "dingtalk",
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

    assert user.dingtalk_source_slug == "dingtalk"
    assert user.dingtalk_corp_id == "ding-corp"
    assert user.dingtalk_userid == "ding-user"
    assert user.name == "张三"
    assert user.department == "销售部"
    assert user.manager_userid == "ding-manager"
    assert "easyauth_authentik_groups" not in request.session
    stored = UserMirror.objects.get(authentik_user_id="ak-user")
    assert stored.dingtalk_source_slug == "dingtalk"
    assert stored.dingtalk_corp_id == "ding-corp"


def test_bind_oidc_session_accepts_authentik_empty_org_context() -> None:
    request = RequestFactory().get("/auth/callback/")
    SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
    request.session.save()
    claims = VerifiedOidcClaims(
        subject="ak-admin",
        name="akadmin",
        email="akadmin@example.test",
        dingtalk_org={
            "corp_id": None,
            "user_id": None,
            "source_slug": "dingtalk",
            "departments": [],
            "manager": None,
            "manager_chain": [],
            "stale": True,
            "last_synced_at": None,
        },
    )

    user = bind_oidc_session(request, claims)

    assert user.authentik_user_id == "ak-admin"
    assert user.name == "akadmin"
    assert user.email == "akadmin@example.test"
    assert user.dingtalk_source_slug == ""
    assert user.dingtalk_corp_id == ""
    assert user.dingtalk_userid == ""
    stored = UserMirror.objects.get(authentik_user_id="ak-admin")
    assert stored.status == "active"
    assert stored.dingtalk_source_slug == ""
