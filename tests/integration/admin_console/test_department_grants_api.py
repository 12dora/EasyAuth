from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final

import pytest
from django.test import Client

from easyauth.accounts.models import (
    USER_STATUS_DISABLED,
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    UserMirror,
)
from easyauth.admin_console.department_grants_api import POLICY_DEPT_GONE_MESSAGE
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.department_policies import (
    POLICY_CREATED_ACTION,
    POLICY_DELETED_ACTION,
    POLICY_UPDATED_ACTION,
)
from easyauth.grants.department_reconcile import DEPARTMENT_GRANT_RECONCILE_TASK_NAME
from easyauth.grants.models import DepartmentGrantPolicy
from easyauth.outbox.models import OutboxEvent
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

if TYPE_CHECKING:
    from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

pytestmark = pytest.mark.django_db

TREE_URL: Final = "/console/api/v1/departments/tree"
POLICIES_URL: Final = "/console/api/v1/departments/{dept_id}/grant-policies"
POLICY_URL: Final = "/console/api/v1/department-grant-policies/{policy_id}"
SOURCE_SLUG: Final = "dingtalk"
CORP_ID: Final = "corp-dept-grants"


def test_department_endpoints_require_auth_and_superuser() -> None:
    anonymous = Client(HTTP_HOST="localhost")
    ordinary = _logged_in_user("dept-grant-ordinary")

    assert anonymous.get(TREE_URL).status_code == HTTPStatus.UNAUTHORIZED
    assert ordinary.get(TREE_URL).status_code == HTTPStatus.FORBIDDEN
    assert (
        ordinary.post(
            POLICIES_URL.format(dept_id="1"),
            data="{}",
            content_type="application/json",
        ).status_code
        == HTTPStatus.FORBIDDEN
    )


def test_departments_tree_conflicts_when_directory_missing_or_multi_corp() -> None:
    client = _logged_in_superuser("dept-grant-tree-conflict")

    missing = client.get(TREE_URL)
    assert missing.status_code == HTTPStatus.CONFLICT
    assert missing.json()["error"]["details"]["reason"] == "directory_not_synced"

    _ = DingTalkDirectorySyncState.objects.create(source_slug=SOURCE_SLUG, corp_id="corp-a")
    _ = DingTalkDirectorySyncState.objects.create(source_slug=SOURCE_SLUG, corp_id="corp-b")
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id="corp-a",
        dept_id="1",
        name="公司A",
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id="corp-b",
        dept_id="1",
        name="公司B",
    )

    multi = client.get(TREE_URL)
    assert multi.status_code == HTTPStatus.CONFLICT
    assert multi.json()["error"]["details"]["reason"] == "multiple_corps"


def test_departments_tree_reports_direct_member_counts() -> None:
    client = _logged_in_superuser("dept-grant-tree-admin")
    _seed_org()
    _ = _bound_user("ak-company", "u-company", ["1"])
    _ = DingTalkUserMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id=CORP_ID,
        user_id="u-sales-only",
        name="仅镜像销售",
        department_ids=["12"],
        status="active",
    )
    _ = _bound_user("ak-team", "u-team", ["99"])

    response = client.get(TREE_URL)

    payload = response.json()["data"]
    root = payload["root"]
    sales = next(child for child in root["children"] if child["dept_id"] == "12")
    team = next(child for child in sales["children"] if child["dept_id"] == "99")
    assert response.status_code == HTTPStatus.OK
    assert payload["source_slug"] == SOURCE_SLUG
    assert payload["corp_id"] == CORP_ID
    assert root["dept_id"] == "1"
    assert root["member_count"] == 1
    assert sales["member_count"] == 1
    assert team["member_count"] == 1
    assert team["children"] == []


def test_department_policies_list_inheritance_and_counts() -> None:
    client = _logged_in_superuser("dept-grant-list-admin")
    _seed_org()
    _ = _bound_user("ak-company-1", "u-company-1", ["1"])
    _ = _bound_user("ak-sales-1", "u-sales-1", ["12"])
    _ = _bound_user("ak-team-1", "u-team-1", ["99"])
    _ = _bound_user("ak-inactive", "u-inactive", ["99"], user_status=USER_STATUS_DISABLED)
    app, group, permission = _catalog("dept-inherit")
    company_policy = _create_policy_via_api(client, dept_id="1", app=app, group=group)
    sales_policy = _create_policy_via_api(
        client,
        dept_id="12",
        app=app,
        permission=permission,
        reason="销售部直接权限",
    )
    team_policy = _create_policy_via_api(
        client,
        dept_id="99",
        app=app,
        group=group,
        reason="本组授权",
    )
    _ = company_policy
    _ = sales_policy
    _ = team_policy

    unknown = client.get(POLICIES_URL.format(dept_id="missing"))
    response = client.get(POLICIES_URL.format(dept_id="99"))

    assert unknown.status_code == HTTPStatus.NOT_FOUND
    assert response.status_code == HTTPStatus.OK
    body = response.json()["data"]
    department = body["department"]
    items = body["items"]
    assert department["dept_id"] == "99"
    assert department["path"] == [
        {"dept_id": "1", "name": "公司"},
        {"dept_id": "12", "name": "销售部"},
        {"dept_id": "99", "name": "销售一组"},
    ]
    assert department["member_count"] == 2
    assert department["subtree_member_count"] == 1
    assert [item["defined_on"]["dept_id"] for item in items] == ["99", "12", "1"]
    team_item = next(item for item in items if item["defined_on"]["dept_id"] == "99")
    company_item = next(item for item in items if item["defined_on"]["dept_id"] == "1")
    sales_item = next(item for item in items if item["defined_on"]["dept_id"] == "12")
    assert team_item["inherited"] is False
    assert company_item["inherited"] is True
    assert company_item["defined_on"]["name"] == "公司"
    assert company_item["affected_user_count"] == 3
    assert sales_item["inherited"] is True
    assert sales_item["affected_user_count"] == 2


def test_department_policies_create_update_delete_audit_and_outbox(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    client = _logged_in_superuser("dept-grant-write-admin")
    _seed_org()
    app, group, permission = _catalog("dept-write")
    other_app, _other_group, _other_permission = _catalog("dept-write-other")

    with django_capture_on_commit_callbacks(execute=True):
        created = client.post(
            POLICIES_URL.format(dept_id="12"),
            data=dumps(
                _policy_payload(
                    app_key=app.app_key,
                    groups=[group.key],
                    directs=[{"permission": permission.key, "scope": "GLOBAL"}],
                ),
            ),
            content_type="application/json",
        )
    empty = client.post(
        POLICIES_URL.format(dept_id="12"),
        data=dumps(_policy_payload(app_key=app.app_key)),
        content_type="application/json",
    )
    policy_id = created.json()["data"]["id"]
    with django_capture_on_commit_callbacks(execute=True):
        updated = client.put(
            POLICY_URL.format(policy_id=policy_id),
            data=dumps(
                {
                    "app_key": app.app_key,
                    "authorization_group_keys": [group.key],
                    "direct_grants": [],
                    "grant_type": "permanent",
                    "grant_expires_at": None,
                    "reason": "更新后的组织授权说明",
                },
            ),
            content_type="application/json",
        )
        locked = client.put(
            POLICY_URL.format(policy_id=policy_id),
            data=dumps(
                {
                    "app_key": other_app.app_key,
                    "authorization_group_keys": [_other_group.key],
                    "direct_grants": [],
                    "grant_type": "permanent",
                    "grant_expires_at": None,
                    "reason": "不能改应用",
                },
            ),
            content_type="application/json",
        )
        deleted = client.delete(POLICY_URL.format(policy_id=policy_id))

    assert created.status_code == HTTPStatus.CREATED
    assert created.json()["data"]["inherited"] is False
    assert created.json()["data"]["authorization_groups"][0]["key"] == group.key
    assert empty.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "至少选择一个授权组或权限" in empty.json()["error"]["details"]["errors"][0]
    assert updated.status_code == HTTPStatus.OK
    assert updated.json()["data"]["reason"] == "更新后的组织授权说明"
    assert updated.json()["data"]["permissions"] == []
    assert locked.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert deleted.status_code == HTTPStatus.NO_CONTENT
    assert not DepartmentGrantPolicy.objects.filter(pk=policy_id).exists()
    assert AuditLog.objects.filter(event_type=POLICY_CREATED_ACTION).exists()
    assert AuditLog.objects.filter(event_type=POLICY_UPDATED_ACTION).exists()
    assert AuditLog.objects.filter(event_type=POLICY_DELETED_ACTION).exists()
    assert OutboxEvent.objects.filter(task_name=DEPARTMENT_GRANT_RECONCILE_TASK_NAME).exists()


def test_update_policy_conflicts_when_department_removed_delete_still_works() -> None:
    client = _logged_in_superuser("dept-grant-gone-dept")
    _seed_org()
    app, group, _permission = _catalog("dept-gone")
    created = _create_policy_via_api(
        client, dept_id="12", app=app, group=group, reason="原销售部策略"
    )
    policy_id = created["id"]
    assert isinstance(policy_id, int)
    original_reason = DepartmentGrantPolicy.objects.get(pk=policy_id).reason
    deleted_count, _ = DingTalkDepartmentMirror.objects.filter(
        source_slug=SOURCE_SLUG,
        corp_id=CORP_ID,
        dept_id="12",
    ).delete()
    assert deleted_count == 1

    updated = client.put(
        POLICY_URL.format(policy_id=policy_id),
        data=dumps(
            {
                "app_key": app.app_key,
                "authorization_group_keys": [group.key],
                "direct_grants": [],
                "grant_type": "permanent",
                "grant_expires_at": None,
                "reason": "部门消失后仍尝试修改",
            },
        ),
        content_type="application/json",
    )

    assert updated.status_code == HTTPStatus.CONFLICT
    error = updated.json()["error"]
    assert error["code"] == "CONFLICT"
    assert error["message"] == POLICY_DEPT_GONE_MESSAGE
    assert error["details"]["reason"] == "department_removed"
    policy = DepartmentGrantPolicy.objects.get(pk=policy_id)
    assert policy.reason == original_reason
    assert not AuditLog.objects.filter(
        event_type=POLICY_UPDATED_ACTION,
        target_id=str(policy_id),
    ).exists()

    deleted = client.delete(POLICY_URL.format(policy_id=policy_id))
    assert deleted.status_code == HTTPStatus.NO_CONTENT
    assert not DepartmentGrantPolicy.objects.filter(pk=policy_id).exists()
    assert AuditLog.objects.filter(
        event_type=POLICY_DELETED_ACTION,
        target_id=str(policy_id),
    ).exists()


def test_department_policies_shared_defined_on_deduplicates_subtree_users() -> None:
    client = _logged_in_superuser("dept-grant-shared-defined")
    _seed_org()
    _ = _bound_user("ak-company-only", "u-company-only", ["1"])
    _ = _bound_user("ak-dual", "u-dual", ["12", "99"])
    _ = _bound_user("ak-team-only", "u-team-only", ["99"])
    app_a, group_a, _permission_a = _catalog("dept-shared-a")
    app_b, group_b, _permission_b = _catalog("dept-shared-b")
    policy_a = _create_policy_via_api(
        client,
        dept_id="12",
        app=app_a,
        group=group_a,
        reason="销售策略甲",
    )
    policy_b = _create_policy_via_api(
        client,
        dept_id="12",
        app=app_b,
        group=group_b,
        reason="销售策略乙",
    )

    response = client.get(POLICIES_URL.format(dept_id="12"))

    assert response.status_code == HTTPStatus.OK
    body = response.json()["data"]
    department = body["department"]
    own = [item for item in body["items"] if item["defined_on"]["dept_id"] == "12"]
    assert {item["id"] for item in own} == {policy_a["id"], policy_b["id"]}
    assert [item["affected_user_count"] for item in own] == [2, 2]
    assert department["dept_id"] == "12"
    assert department["member_count"] == 1
    assert department["subtree_member_count"] == 2


def _seed_org() -> None:
    _ = DingTalkDirectorySyncState.objects.create(source_slug=SOURCE_SLUG, corp_id=CORP_ID)
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id=CORP_ID,
        dept_id="1",
        parent_id="",
        name="公司",
        order=1,
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id=CORP_ID,
        dept_id="12",
        parent_id="1",
        name="销售部",
        order=1,
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id=CORP_ID,
        dept_id="99",
        parent_id="12",
        name="销售一组",
        order=1,
    )


def _bound_user(
    authentik_user_id: str,
    ding_user_id: str,
    department_ids: list[str],
    *,
    user_status: str = "active",
) -> UserMirror:
    _ = DingTalkUserMirror.objects.create(
        source_slug=SOURCE_SLUG,
        corp_id=CORP_ID,
        user_id=ding_user_id,
        name=authentik_user_id,
        department_ids=department_ids,
        status="active",
    )
    return UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        name=authentik_user_id,
        status=user_status,
        dingtalk_source_slug=SOURCE_SLUG,
        dingtalk_corp_id=CORP_ID,
        dingtalk_userid=ding_user_id,
    )


def _catalog(prefix: str) -> tuple[App, AuthorizationGroup, Permission]:
    app = App.objects.create(app_key=f"{prefix}-app", name=prefix, alias=prefix)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    permission = Permission.objects.create(
        app=app,
        key=f"{prefix}.view",
        name="查看",
        supported_scopes=["GLOBAL"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key=f"{prefix}-role",
        kind="role",
        name=prefix,
        requestable=False,
    )
    return app, group, permission


def _create_policy_via_api(  # noqa: PLR0913 - 测试夹具需要显式覆盖部门、应用与授权目标。
    client: Client,
    *,
    dept_id: str,
    app: App,
    group: AuthorizationGroup | None = None,
    permission: Permission | None = None,
    reason: str = "组织授权",
) -> dict[str, object]:
    payload = _policy_payload(
        app_key=app.app_key,
        groups=[] if group is None else [group.key],
        directs=[] if permission is None else [{"permission": permission.key, "scope": "GLOBAL"}],
        reason=reason,
    )
    response = client.post(
        POLICIES_URL.format(dept_id=dept_id),
        data=dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == HTTPStatus.CREATED
    return response.json()["data"]


def _policy_payload(
    *,
    app_key: str,
    groups: list[str] | None = None,
    directs: list[dict[str, str]] | None = None,
    reason: str = "组织授权",
) -> dict[str, object]:
    return {
        "source_slug": SOURCE_SLUG,
        "corp_id": CORP_ID,
        "app_key": app_key,
        "authorization_group_keys": groups or [],
        "direct_grants": directs or [],
        "grant_type": "permanent",
        "grant_expires_at": None,
        "reason": reason,
    }


def _logged_in_user(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_user(client, username)
    return client


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_admin(client, username)
    return client
