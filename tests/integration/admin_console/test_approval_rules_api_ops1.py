from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import ClassVar, Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import BaseModel, ConfigDict

from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AuthorizationGroup,
    Permission,
)

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-approval-rules"


class ApprovalRuleItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: int
    target_type: str
    target_key: str
    approver_type: str
    approver_userids: list[str]
    is_active: bool


class ApprovalRuleEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    approval_rule: ApprovalRuleItem


class ApprovalRuleListEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    data: list[ApprovalRuleItem]


def test_ops1_owner_creates_reads_and_updates_approval_rule() -> None:
    # Given: owner 管理一个 requestable AuthorizationGroup, 该授权组尚无审批规则。
    client = _logged_in_user("ops1-rule-owner")
    app = _member_app("ops1-rule-owner-app", "ops1-rule-owner", role="owner")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="Auditor",
        requestable=True,
    )

    # When: owner 创建、读取并更新该 AuthorizationGroup 的 ApprovalRule。
    created = client.post(
        _rules_url(app.app_key),
        data=_rule_payload(
            target_type="authorization_group",
            target_key=group.key,
            approver_userids=("manager-001",),
            is_active=True,
        ),
        content_type="application/json",
    )
    listed = client.get(_rules_url(app.app_key))
    created_body = ApprovalRuleEnvelope.model_validate_json(created.content)
    rule_id = created_body.approval_rule.id
    updated = client.patch(
        _rule_url(app.app_key, rule_id),
        data=_patch_payload(approver_userids=("manager-002", "manager-003"), is_active=False),
        content_type="application/json",
    )

    # Then: API 返回稳定字段, 数据库中保留同一个 ApprovalRule 并写入更新值。
    listed_body = ApprovalRuleListEnvelope.model_validate_json(listed.content)
    updated_body = ApprovalRuleEnvelope.model_validate_json(updated.content)
    assert created.status_code == HTTPStatus.CREATED
    assert created_body.approval_rule.model_dump() == {
        "id": rule_id,
        "target_type": "authorization_group",
        "target_key": "auditor",
        "approver_type": "dingtalk_userids",
        "approver_userids": ["manager-001"],
        "is_active": True,
    }
    assert listed.status_code == HTTPStatus.OK
    assert listed_body.data == [created_body.approval_rule]
    assert updated.status_code == HTTPStatus.OK
    assert updated_body.approval_rule.model_dump() == {
        "id": rule_id,
        "target_type": "authorization_group",
        "target_key": "auditor",
        "approver_type": "dingtalk_userids",
        "approver_userids": ["manager-002", "manager-003"],
        "is_active": False,
    }
    rule = ApprovalRule.objects.get(id=rule_id)
    assert rule.authorization_group == group
    assert rule.role is None
    assert rule.approver_userids == ["manager-002", "manager-003"]
    assert rule.is_active is False


def test_ops1_superuser_manages_approval_rules_without_membership() -> None:
    # Given: App 无成员关系, 但系统管理员已登录。
    client = _logged_in_superuser("ops1-rule-admin")
    app = App.objects.create(app_key="ops1-rule-admin-app", name="Admin App")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
        requestable=True,
    )

    # When: superuser 创建、读取并禁用 ApprovalRule。
    created = client.post(
        _rules_url(app.app_key),
        data=_rule_payload(
            target_type="authorization_group",
            target_key=group.key,
            approver_userids=("manager-010",),
            is_active=True,
        ),
        content_type="application/json",
    )
    listed = client.get(_rules_url(app.app_key))
    created_body = ApprovalRuleEnvelope.model_validate_json(created.content)
    updated = client.patch(
        _rule_url(app.app_key, created_body.approval_rule.id),
        data=_patch_payload(approver_userids=("manager-010",), is_active=False),
        content_type="application/json",
    )

    # Then: superuser 不需要 AppMembership 即可完成读写。
    assert created.status_code == HTTPStatus.CREATED
    assert listed.status_code == HTTPStatus.OK
    listed_body = ApprovalRuleListEnvelope.model_validate_json(listed.content)
    updated_body = ApprovalRuleEnvelope.model_validate_json(updated.content)
    assert listed_body.data[0].target_key == "operator"
    assert updated.status_code == HTTPStatus.OK
    assert updated_body.approval_rule.is_active is False


def test_ops1_developer_reads_but_cannot_write_approval_rules() -> None:
    # Given: developer 是 App active 成员, App 已有 ApprovalRule。
    client = _logged_in_user("ops1-rule-developer")
    app = _member_app("ops1-rule-developer-app", "ops1-rule-developer", role="developer")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="viewer",
        kind="role",
        name="Viewer",
        requestable=True,
    )
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )

    # When: developer 读取、创建并更新 ApprovalRule。
    listed = client.get(_rules_url(app.app_key))
    created = client.post(
        _rules_url(app.app_key),
        data=_rule_payload(
            target_type="authorization_group",
            target_key=group.key,
            approver_userids=("manager-002",),
            is_active=True,
        ),
        content_type="application/json",
    )
    listed_body = ApprovalRuleListEnvelope.model_validate_json(listed.content)
    updated = client.patch(
        _rule_url(app.app_key, listed_body.data[0].id),
        data=_patch_payload(approver_userids=("manager-003",), is_active=False),
        content_type="application/json",
    )

    # Then: developer 可读但不能写, 原规则不被修改。
    assert listed.status_code == HTTPStatus.OK
    assert [item.model_dump() for item in listed_body.data] == [
        {
            "id": listed_body.data[0].id,
            "target_type": "authorization_group",
            "target_key": "viewer",
            "approver_type": "dingtalk_userids",
            "approver_userids": ["manager-001"],
            "is_active": True,
        },
    ]
    assert created.status_code == HTTPStatus.FORBIDDEN
    assert updated.status_code == HTTPStatus.FORBIDDEN
    rule.refresh_from_db()
    assert rule.approver_userids == ["manager-001"]
    assert rule.is_active is True


def test_ops1_non_member_cannot_read_approval_rules() -> None:
    # Given: 普通用户不属于目标 App。
    client = _logged_in_user("ops1-rule-outsider")
    app = App.objects.create(app_key="ops1-rule-outsider-app", name="Outsider App")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="viewer",
        kind="role",
        name="Viewer",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )

    # When: 普通用户读取该 App 的 ApprovalRule。
    response = client.get(_rules_url(app.app_key))

    # Then: API 拒绝非成员访问且不泄漏规则内容。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "manager-001" not in response.content.decode()


def test_ops1_owner_manages_permission_approval_rule_with_document_target_fields() -> None:
    # Given: owner 管理同一 App 下的 Permission, 且另一个 App 有同名 Permission。
    client = _logged_in_user("ops1-rule-permission-owner")
    app = _member_app("ops1-rule-permission-app", "ops1-rule-permission-owner", role="owner")
    permission = Permission.objects.create(app=app, key="report.read", name="Report Read")
    other_app = App.objects.create(app_key="ops1-rule-permission-other", name="Other")
    _ = Permission.objects.create(app=other_app, key="report.read", name="Other Report Read")

    # When: owner 按文档 target 字段创建、读取并更新 Permission ApprovalRule。
    created = client.post(
        _rules_url(app.app_key),
        data=dumps(
            {
                "target_type": "permission",
                "target_key": permission.key,
                "approver_userids": ["manager-010"],
                "is_active": True,
            },
        ),
        content_type="application/json",
    )
    listed = client.get(_rules_url(app.app_key))
    created_body = ApprovalRuleEnvelope.model_validate_json(created.content)
    rule_id = created_body.approval_rule.id
    updated = client.patch(
        _rule_url(app.app_key, rule_id),
        data=dumps({"approver_userids": ["manager-011"], "is_active": False}),
        content_type="application/json",
    )
    cross_app = client.post(
        _rules_url(app.app_key),
        data=dumps(
            {
                "target_type": "permission",
                "target_key": "missing.from.current.app",
                "approver_userids": ["manager-012"],
            },
        ),
        content_type="application/json",
    )

    # Then: API 返回 target_type/target_key, 并拒绝非本 App 目标。
    rule = ApprovalRule.objects.get(id=rule_id)
    assert created.status_code == HTTPStatus.CREATED
    assert listed.status_code == HTTPStatus.OK
    assert updated.status_code == HTTPStatus.OK
    listed_body = ApprovalRuleListEnvelope.model_validate_json(listed.content)
    updated_body = ApprovalRuleEnvelope.model_validate_json(updated.content)
    assert created_body.approval_rule.target_type == "permission"
    assert created_body.approval_rule.target_key == "report.read"
    assert listed_body.data[0].target_type == "permission"
    assert updated_body.approval_rule.approver_userids == ["manager-011"]
    assert cross_app.status_code == HTTPStatus.BAD_REQUEST
    assert rule.permission == permission
    assert rule.role is None
    assert rule.approver_userids == ["manager-011"]


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _rules_url(app_key: str) -> str:
    return f"/console/api/v1/apps/{app_key}/approval-rules"


def _rule_url(app_key: str, rule_id: int) -> str:
    return f"{_rules_url(app_key)}/{rule_id}"


def _rule_payload(
    *,
    target_type: str,
    target_key: str,
    approver_userids: tuple[str, ...],
    is_active: bool,
) -> str:
    return dumps(
        {
            "target_type": target_type,
            "target_key": target_key,
            "approver_type": "dingtalk_userids",
            "approver_userids": list(approver_userids),
            "is_active": is_active,
        },
    )


def _patch_payload(*, approver_userids: tuple[str, ...], is_active: bool) -> str:
    return dumps(
        {
            "approver_type": "dingtalk_userids",
            "approver_userids": list(approver_userids),
            "is_active": is_active,
        },
    )
