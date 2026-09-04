from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    DECISION_ACTOR_USER,
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_WITHDRAWN,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.portal.access_request_data import (
    APPROVER_PREFETCH,
    AccessRequestDecisionActorMissingError,
    access_request_items,
    access_request_items_for_user,
)
from tests.integration.portal.helpers import logged_in_client
from tests.integration.portal.json_helpers import HttpResponseLike, json_object

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
# 主查询 + 审批人 prefetch + 授权组批量 + direct grant 批量 + 决定人 UserMirror 批量。
EXPECTED_MIXED_ROW_QUERIES: Final = 5
EXPECTED_MIXED_ROW_COUNT: Final = 6
# session + 当前用户 + COUNT + 页切片 + 审批人 prefetch + 授权组批量 + direct grant 批量
# + 决定人 UserMirror 批量; 真实 HTTP 路径固定 8 条, 不随行数增长。
EXPECTED_MIXED_ROW_HTTP_QUERIES: Final = 8


def test_my_requests_list_shows_current_approvers_for_submitted() -> None:
    # Given: 员工有一条待审批申请, 按创建顺序挂了两名审批人。
    client, user = logged_in_client("list-approvers-submitted-user")
    app = App.objects.create(app_key="list-approvers-submitted-app", name="CRM")
    later_name = UserMirror.objects.create(
        authentik_user_id="list-approvers-yi",
        name="乙审批人",
        status=USER_STATUS_ACTIVE,
    )
    earlier_name = UserMirror.objects.create(
        authentik_user_id="list-approvers-jia",
        name="甲审批人",
        status=USER_STATUS_ACTIVE,
    )
    access_request = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        idempotency_key="list-approvers-submitted",
    )
    first_assignment = AccessRequestApprover.objects.create(
        access_request=access_request,
        approver=later_name,
    )
    second_assignment = AccessRequestApprover.objects.create(
        access_request=access_request,
        approver=earlier_name,
    )

    # When: 员工读取「我的申请」列表。
    response = client.get(REQUESTS_API_URL)

    # Then: submitted 行按分配 id 升序返回审批人姓名, 决定人为空, 三个时间戳均为 null。
    assert response.status_code == HTTPStatus.OK
    row = _row_by_id(response, access_request.id)
    assert first_assignment.id < second_assignment.id
    assert row["current_approvers"] == [
        {"user_id": later_name.authentik_user_id, "name": "乙审批人"},
        {"user_id": earlier_name.authentik_user_id, "name": "甲审批人"},
    ]
    assert row["decided_by"] == ""
    assert row["decision_actor_type"] == ""
    assert row["decided_by_name"] is None
    assert row["approved_at"] is None
    assert row["applied_at"] is None
    assert row["withdrawn_at"] is None


def test_my_requests_list_hides_approvers_and_resolves_decided_by_name() -> None:
    # Given: 员工有一条已通过申请, 决定人存在 UserMirror, 且仍留着审批人分配。
    client, user = logged_in_client("list-approvers-approved-user")
    app = App.objects.create(app_key="list-approvers-approved-app", name="CRM")
    approver = UserMirror.objects.create(
        authentik_user_id="list-approvers-decider",
        name="已决审批人",
        status=USER_STATUS_ACTIVE,
    )
    access_request = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-approved",
        decided_by=approver.authentik_user_id,
    )
    _ = AccessRequestApprover.objects.create(access_request=access_request, approver=approver)

    # When: 员工读取「我的申请」列表。
    response = client.get(REQUESTS_API_URL)

    # Then: 已决行审批人列为空, decided_by 保留原始 id, 姓名从 UserMirror 解析。
    assert response.status_code == HTTPStatus.OK
    row = _row_by_id(response, access_request.id)
    assert row["current_approvers"] == []
    assert row["decided_by"] == approver.authentik_user_id
    assert row["decision_actor_type"] == DECISION_ACTOR_USER
    assert row["decided_by_name"] == "已决审批人"
    assert row["approved_at"] == access_request.approved_at.isoformat()
    assert row["applied_at"] is None
    assert row["withdrawn_at"] is None


def test_my_requests_list_withdrawn_has_empty_approvers_and_null_decided_by_name() -> None:
    # Given: 员工有一条已撤回申请, 历史上仍挂着审批人。
    client, user = logged_in_client("list-approvers-withdrawn-user")
    app = App.objects.create(app_key="list-approvers-withdrawn-app", name="CRM")
    approver = UserMirror.objects.create(
        authentik_user_id="list-approvers-withdrawn-approver",
        name="原审批人",
        status=USER_STATUS_ACTIVE,
    )
    access_request = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_WITHDRAWN,
        idempotency_key="list-approvers-withdrawn",
    )
    _ = AccessRequestApprover.objects.create(access_request=access_request, approver=approver)

    # When: 员工读取「我的申请」列表。
    response = client.get(REQUESTS_API_URL)

    # Then: 撤回行审批人列为空, 决定人姓名为 null。
    assert response.status_code == HTTPStatus.OK
    row = _row_by_id(response, access_request.id)
    assert row["current_approvers"] == []
    assert row["decided_by"] == ""
    assert row["decision_actor_type"] == ""
    assert row["decided_by_name"] is None
    assert row["approved_at"] is None
    assert row["applied_at"] is None
    assert row["withdrawn_at"] == access_request.withdrawn_at.isoformat()


def test_my_requests_list_resolves_approver_and_decider_names_in_fixed_queries() -> None:
    # Given: 同一员工有多条 submitted / approved / withdrawn, 避免按行打查询。
    _client, user = logged_in_client("list-approvers-query-user")
    app = App.objects.create(app_key="list-approvers-query-app", name="CRM")
    first_approver = UserMirror.objects.create(
        authentik_user_id="list-approvers-query-a",
        name="查询审批人甲",
        status=USER_STATUS_ACTIVE,
    )
    second_approver = UserMirror.objects.create(
        authentik_user_id="list-approvers-query-b",
        name="查询审批人乙",
        status=USER_STATUS_ACTIVE,
    )
    decider = UserMirror.objects.create(
        authentik_user_id="list-approvers-query-decider",
        name="查询决定人",
        status=USER_STATUS_ACTIVE,
    )
    for index in range(3):
        submitted = _create_request(
            user=user,
            app=app,
            status=REQUEST_STATUS_SUBMITTED,
            idempotency_key=f"list-approvers-query-submitted-{index}",
        )
        _ = AccessRequestApprover.objects.create(
            access_request=submitted,
            approver=first_approver,
        )
        _ = AccessRequestApprover.objects.create(
            access_request=submitted,
            approver=second_approver,
        )
    approved = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-query-approved",
        decided_by=decider.authentik_user_id,
    )
    _ = AccessRequestApprover.objects.create(access_request=approved, approver=decider)
    withdrawn = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_WITHDRAWN,
        idempotency_key="list-approvers-query-withdrawn",
    )
    _ = AccessRequestApprover.objects.create(access_request=withdrawn, approver=first_approver)
    extra_approved = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-query-approved-2",
        decided_by=decider.authentik_user_id,
    )
    _ = AccessRequestApprover.objects.create(access_request=extra_approved, approver=decider)

    # When: 门户按真实列表路径批量 hydrate。
    with CaptureQueriesContext(connection) as captured_queries:
        items = access_request_items_for_user(user)

    # Then: 查询数固定, submitted 带审批人, 已决只解析决定人姓名, 撤回为空。
    assert len(items) == EXPECTED_MIXED_ROW_COUNT
    assert len(captured_queries) == EXPECTED_MIXED_ROW_QUERIES
    by_status: dict[str, list[dict[str, JsonValue]]] = {}
    for item in items:
        status = item["status"]
        assert isinstance(status, str)
        by_status.setdefault(status, []).append(item)
    assert {item["decided_by_name"] for item in by_status[REQUEST_STATUS_APPROVED]} == {
        "查询决定人",
    }
    for item in by_status[REQUEST_STATUS_APPROVED]:
        assert item["current_approvers"] == []
    for item in by_status[REQUEST_STATUS_SUBMITTED]:
        assert item["current_approvers"] == [
            {"user_id": first_approver.authentik_user_id, "name": "查询审批人甲"},
            {"user_id": second_approver.authentik_user_id, "name": "查询审批人乙"},
        ]
        assert item["decided_by_name"] is None
    withdrawn_item = by_status[REQUEST_STATUS_WITHDRAWN][0]
    assert withdrawn_item["current_approvers"] == []
    assert withdrawn_item["decided_by_name"] is None


def test_my_requests_list_http_resolves_approvers_in_fixed_queries() -> None:
    # Given: 同一员工有多条 submitted / approved / withdrawn, 走真实 HTTP 列表。
    client, user = logged_in_client("list-approvers-http-query-user")
    app = App.objects.create(app_key="list-approvers-http-query-app", name="CRM")
    first_approver = UserMirror.objects.create(
        authentik_user_id="list-approvers-http-query-a",
        name="HTTP 审批人甲",
        status=USER_STATUS_ACTIVE,
    )
    second_approver = UserMirror.objects.create(
        authentik_user_id="list-approvers-http-query-b",
        name="HTTP 审批人乙",
        status=USER_STATUS_ACTIVE,
    )
    decider = UserMirror.objects.create(
        authentik_user_id="list-approvers-http-query-decider",
        name="HTTP 决定人",
        status=USER_STATUS_ACTIVE,
    )
    for index in range(3):
        submitted = _create_request(
            user=user,
            app=app,
            status=REQUEST_STATUS_SUBMITTED,
            idempotency_key=f"list-approvers-http-query-submitted-{index}",
        )
        _ = AccessRequestApprover.objects.create(
            access_request=submitted,
            approver=first_approver,
        )
        _ = AccessRequestApprover.objects.create(
            access_request=submitted,
            approver=second_approver,
        )
    approved = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-http-query-approved",
        decided_by=decider.authentik_user_id,
    )
    _ = AccessRequestApprover.objects.create(access_request=approved, approver=decider)
    withdrawn = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_WITHDRAWN,
        idempotency_key="list-approvers-http-query-withdrawn",
    )
    _ = AccessRequestApprover.objects.create(access_request=withdrawn, approver=first_approver)
    extra_approved = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-http-query-approved-2",
        decided_by=decider.authentik_user_id,
    )
    _ = AccessRequestApprover.objects.create(access_request=extra_approved, approver=decider)

    # When: 员工读取「我的申请」真实 HTTP 列表。
    with CaptureQueriesContext(connection) as captured_queries:
        response = client.get(REQUESTS_API_URL)

    # Then: 查询数固定, 覆盖 session/鉴权/count/分页/序列化, 不随行数增长。
    assert response.status_code == HTTPStatus.OK
    payload = json_object(response)
    data = payload["data"]
    assert isinstance(data, list)
    assert len(data) == EXPECTED_MIXED_ROW_COUNT
    assert len(captured_queries) == EXPECTED_MIXED_ROW_HTTP_QUERIES
    by_status: dict[str, list[dict[str, JsonValue]]] = {}
    for item in data:
        assert isinstance(item, dict)
        status = item["status"]
        assert isinstance(status, str)
        by_status.setdefault(status, []).append(item)
    assert {item["decided_by_name"] for item in by_status[REQUEST_STATUS_APPROVED]} == {
        "HTTP 决定人",
    }
    for item in by_status[REQUEST_STATUS_APPROVED]:
        assert item["current_approvers"] == []
    for item in by_status[REQUEST_STATUS_SUBMITTED]:
        assert item["current_approvers"] == [
            {"user_id": first_approver.authentik_user_id, "name": "HTTP 审批人甲"},
            {"user_id": second_approver.authentik_user_id, "name": "HTTP 审批人乙"},
        ]
        assert item["decided_by_name"] is None
    withdrawn_item = by_status[REQUEST_STATUS_WITHDRAWN][0]
    assert withdrawn_item["current_approvers"] == []
    assert withdrawn_item["decided_by_name"] is None


def test_my_requests_list_console_admin_decision_has_null_decided_by_name() -> None:
    # Given: 控制台管理员代审通过, decided_by 不是 UserMirror 主键。
    client, user = logged_in_client("list-approvers-console-admin-user")
    app = App.objects.create(app_key="list-approvers-console-admin-app", name="CRM")
    access_request = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-console-admin",
        decided_by="console-admin-actor",
    )
    access_request.decision_actor_type = DECISION_ACTOR_CONSOLE_ADMIN
    access_request.save(update_fields=["decision_actor_type"])

    # When: 员工读取「我的申请」列表。
    response = client.get(REQUESTS_API_URL)

    # Then: 控制台代审不解析姓名, decided_by_name 为 null。
    assert response.status_code == HTTPStatus.OK
    row = _row_by_id(response, access_request.id)
    assert row["decided_by"] == "console-admin-actor"
    assert row["decision_actor_type"] == DECISION_ACTOR_CONSOLE_ADMIN
    assert row["decided_by_name"] is None


def test_user_actor_decision_without_user_mirror_raises() -> None:
    # Given: 站内用户决定, 但 decided_by 没有对应 UserMirror。
    _client, user = logged_in_client("list-approvers-missing-mirror-user")
    app = App.objects.create(app_key="list-approvers-missing-mirror-app", name="CRM")
    access_request = _create_request(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        idempotency_key="list-approvers-missing-mirror",
        decided_by="missing-decider-id",
    )
    prefetched = (
        AccessRequest.objects.select_related("app")
        .prefetch_related(APPROVER_PREFETCH)
        .get(pk=access_request.id)
    )

    # When / Then: 用户决定缺少镜像是数据损坏, 必须失败而不是 silent null。
    with pytest.raises(AccessRequestDecisionActorMissingError, match="missing-decider-id"):
        access_request_items((prefetched,))


def _create_request(
    *,
    user: UserMirror,
    app: App,
    status: str,
    idempotency_key: str,
    decided_by: str = "",
) -> AccessRequest:
    decided_at = timezone.now() if status == REQUEST_STATUS_APPROVED else None
    withdrawn_at = timezone.now() if status == REQUEST_STATUS_WITHDRAWN else None
    return AccessRequest.objects.create(
        user=user,
        app=app,
        status=status,
        grant_type=GRANT_TYPE_PERMANENT,
        reason=idempotency_key,
        idempotency_key=idempotency_key,
        payload_digest="d" * 64,
        approved_at=decided_at,
        decided_at=decided_at,
        decided_by=decided_by,
        decision_actor_type=DECISION_ACTOR_USER if decided_by else "",
        withdrawn_at=withdrawn_at,
    )


def _row_by_id(response: HttpResponseLike, request_id: int) -> dict[str, JsonValue]:
    payload = json_object(response)
    data = payload["data"]
    assert isinstance(data, list)
    matches = [
        item for item in data if isinstance(item, dict) and item["id"] == request_id
    ]
    assert len(matches) == 1
    return matches[0]
