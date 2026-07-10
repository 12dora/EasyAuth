from __future__ import annotations

from http import HTTPStatus

import pytest

from easyauth.admin_console.query_test_api import _success_payload
from easyauth.admin_console.query_tester import PermissionQueryTestResult
from easyauth.applications.models import App
from easyauth.grants.query import ExpandedGrant, ResolvedManagedUsers

pytestmark = pytest.mark.django_db


def test_query_test_success_payload_serializes_resolved_managed_users() -> None:
    # Given: 联调结果包含 MANAGED_USERS resolved。
    app = App.objects.create(app_key="crm-query-test-managed-users", name="CRM")
    result = PermissionQueryTestResult(
        status_code=HTTPStatus.OK,
        code="ok",
        explanation="权限查询成功。",
        grants=(
            ExpandedGrant(
                permission="customer.profile.view",
                scope="MANAGED_USERS",
                source_type="group",
                source_key="team-manager",
                expires_at=None,
                resolved=ResolvedManagedUsers(
                    user_ids=("bob",),
                    resolver="dingtalk_manager_chain",
                    resolved_at="2026-07-02T12:00:00+08:00",
                ),
            ),
        ),
    )

    # When: 生成控制台联调成功响应。
    payload = _success_payload(app=app, user_id="alice", result=result)

    # Then: grants 中保留 resolved 结构。
    assert payload["grants"] == [
        {
            "permission": "customer.profile.view",
            "scope": "MANAGED_USERS",
            "source_type": "group",
            "source_key": "team-manager",
            "resolved": {
                "user_ids": ["bob"],
                "resolver": "dingtalk_manager_chain",
                "resolved_at": "2026-07-02T12:00:00+08:00",
            },
        },
    ]
