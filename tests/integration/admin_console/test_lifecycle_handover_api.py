from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import JsonValue
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.inputs import AuthorizationGroupGrantInput
from easyauth.grants.models import AccessGrant
from easyauth.grants.services import GrantMutationInput, GrantService
from easyauth.lifecycle import services as lifecycle_services
from easyauth.lifecycle.models import (
    HandoverAppAction,
    HandoverTask,
    OnboardingTemplate,
    OnboardingTemplateItem,
    TransferPlan,
)
from easyauth.lifecycle.services import HandoverConflictError, update_action_receiver

if TYPE_CHECKING:
    from easyauth.grants.inputs import ScopedDirectGrantInput

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-lifecycle-handover"
TASKS_URL: Final = "/console/api/v1/lifecycle/handover-tasks"
SECOND_UPDATE_CALL: Final = 2
CONCURRENT_CONFLICT_MESSAGE: Final = "并发状态冲突。"
SECOND_TEMPLATE_SAVE_ERROR: Final = "第二个模板项写入失败"
SECOND_GRANT_WRITE_ERROR: Final = "第二个应用授权失败"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def test_handover_task_list_uses_standard_server_pagination() -> None:
    client = _logged_in_superuser("handover-pagination-admin")
    for index in range(3):
        subject = UserMirror.objects.create(authentik_user_id=f"handover-page-subject-{index}")
        _ = HandoverTask.objects.create(kind="offboard", subject_user=subject)

    response = client.get(TASKS_URL, {"page": "2", "page_size": "1"})

    body = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(body, dict)
    data = body["data"]
    assert isinstance(data, list)
    assert response.status_code == HTTPStatus.OK
    assert len(data) == 1
    assert body["pagination"] == {
        "page": 2,
        "page_size": 1,
        "total_items": 3,
        "total_pages": 3,
    }


def test_receiver_batch_rolls_back_all_updates_when_one_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("handover-receiver-atomic-admin")
    subject = UserMirror.objects.create(authentik_user_id="handover-receiver-subject")
    receiver = UserMirror.objects.create(authentik_user_id="handover-receiver-target")
    task = HandoverTask.objects.create(kind="offboard", subject_user=subject)
    first_app = App.objects.create(app_key="handover-atomic-a", name="Atomic A")
    second_app = App.objects.create(app_key="handover-atomic-b", name="Atomic B")
    first_action = HandoverAppAction.objects.create(task=task, app=first_app)
    second_action = HandoverAppAction.objects.create(task=task, app=second_app)
    real_update = update_action_receiver
    call_count = 0

    def fail_second_update(
        *,
        action: HandoverAppAction,
        to_user: UserMirror | None,
        policy: dict[str, JsonValue],
    ) -> HandoverAppAction:
        nonlocal call_count
        call_count += 1
        if call_count == SECOND_UPDATE_CALL:
            raise HandoverConflictError(CONCURRENT_CONFLICT_MESSAGE)
        return real_update(action=action, to_user=to_user, policy=policy)

    monkeypatch.setattr(
        "easyauth.admin_console.lifecycle_api.update_action_receiver",
        fail_second_update,
    )

    response = client.patch(
        f"{TASKS_URL}/{task.id}",
        data=dumps(
            {
                "app_actions": [
                    {
                        "app_key": first_app.app_key,
                        "to_user_id": receiver.authentik_user_id,
                        "release_to_pool": False,
                    },
                    {
                        "app_key": second_app.app_key,
                        "to_user_id": receiver.authentik_user_id,
                        "release_to_pool": False,
                    },
                ],
            },
        ),
        content_type="application/json",
    )

    first_action.refresh_from_db()
    second_action.refresh_from_db()
    assert response.status_code == HTTPStatus.CONFLICT
    assert first_action.to_user is None
    assert second_action.to_user is None


@pytest.mark.parametrize(
    "strategy",
    [
        ("handover-xor-receiver", True),
        (None, False),
    ],
)
def test_receiver_requires_exactly_one_transfer_strategy(
    strategy: tuple[str | None, bool],
) -> None:
    to_user_id, release_to_pool = strategy
    client = _logged_in_superuser(f"handover-xor-admin-{release_to_pool}")
    subject = UserMirror.objects.create(authentik_user_id="handover-xor-subject")
    _ = UserMirror.objects.create(authentik_user_id="handover-xor-receiver")
    task = HandoverTask.objects.create(kind="offboard", subject_user=subject)
    app = App.objects.create(app_key="handover-xor-app", name="XOR App")
    action = HandoverAppAction.objects.create(task=task, app=app)

    response = client.patch(
        f"{TASKS_URL}/{task.id}",
        data=dumps(
            {
                "app_actions": [
                    {
                        "app_key": app.app_key,
                        "to_user_id": to_user_id,
                        "release_to_pool": release_to_pool,
                    },
                ],
            },
        ),
        content_type="application/json",
    )

    action.refresh_from_db()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert action.to_user is None
    assert action.policy == {}


def test_receiver_rejects_handover_subject() -> None:
    client = _logged_in_superuser("handover-self-receiver-admin")
    subject = UserMirror.objects.create(authentik_user_id="handover-self-receiver-subject")
    task = HandoverTask.objects.create(kind="offboard", subject_user=subject)
    app = App.objects.create(app_key="handover-self-receiver-app", name="Self Receiver")
    action = HandoverAppAction.objects.create(task=task, app=app)

    response = client.patch(
        f"{TASKS_URL}/{task.id}",
        data=dumps(
            {
                "app_actions": [
                    {
                        "app_key": app.app_key,
                        "to_user_id": subject.authentik_user_id,
                        "release_to_pool": False,
                    },
                ],
            },
        ),
        content_type="application/json",
    )

    action.refresh_from_db()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert action.to_user is None
    assert action.policy == {}


def test_receiver_batch_semantic_error_prevents_all_writes() -> None:
    client = _logged_in_superuser("handover-receiver-semantic-atomic-admin")
    subject = UserMirror.objects.create(authentik_user_id="handover-semantic-subject")
    receiver = UserMirror.objects.create(authentik_user_id="handover-semantic-receiver")
    task = HandoverTask.objects.create(kind="offboard", subject_user=subject)
    first_app = App.objects.create(app_key="handover-semantic-a", name="Semantic A")
    second_app = App.objects.create(app_key="handover-semantic-b", name="Semantic B")
    first_action = HandoverAppAction.objects.create(task=task, app=first_app)
    second_action = HandoverAppAction.objects.create(task=task, app=second_app)

    response = client.patch(
        f"{TASKS_URL}/{task.id}",
        data=dumps(
            {
                "app_actions": [
                    {
                        "app_key": first_app.app_key,
                        "to_user_id": receiver.authentik_user_id,
                        "release_to_pool": False,
                    },
                    {
                        "app_key": second_app.app_key,
                        "to_user_id": subject.authentik_user_id,
                        "release_to_pool": False,
                    },
                ],
            },
        ),
        content_type="application/json",
    )

    first_action.refresh_from_db()
    second_action.refresh_from_db()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert first_action.to_user is None
    assert first_action.policy == {}
    assert second_action.to_user is None
    assert second_action.policy == {}


def test_template_replacement_rolls_back_when_second_item_save_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("handover-template-atomic-admin")
    old_app, _old_group, old_permission = _app_with_catalog("handover-template-old")
    first_app, _first_group, first_permission = _app_with_catalog("handover-template-new-a")
    second_app, _second_group, second_permission = _app_with_catalog("handover-template-new-b")
    template = OnboardingTemplate.objects.create(
        name="原岗位模板",
        description="原模板说明",
    )
    old_item = OnboardingTemplateItem.objects.create(
        template=template,
        app=old_app,
        permission=old_permission,
        scope_key="GLOBAL",
    )
    real_save = OnboardingTemplateItem.save
    save_count = 0

    def fail_second_item_save(
        item: OnboardingTemplateItem,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal save_count
        save_count += 1
        if save_count == SECOND_UPDATE_CALL:
            raise RuntimeError(SECOND_TEMPLATE_SAVE_ERROR)
        real_save(item, *args, **kwargs)

    monkeypatch.setattr(OnboardingTemplateItem, "save", fail_second_item_save)

    response = client.patch(
        f"/console/api/v1/lifecycle/onboarding-templates/{template.id}",
        data=dumps(
            {
                "name": "新岗位模板",
                "description": "新模板说明",
                "is_active": True,
                "items": [
                    {
                        "app_key": first_app.app_key,
                        "permission_key": first_permission.key,
                        "scope_key": "GLOBAL",
                    },
                    {
                        "app_key": second_app.app_key,
                        "permission_key": second_permission.key,
                        "scope_key": "GLOBAL",
                    },
                ],
            },
        ),
        content_type="application/json",
    )

    template.refresh_from_db()
    stored_items = list(OnboardingTemplateItem.objects.filter(template=template))
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert template.name == "原岗位模板"
    assert template.description == "原模板说明"
    assert [item.id for item in stored_items] == [old_item.id]


def test_onboard_multiple_apps_rolls_back_when_second_grant_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("handover-onboard-atomic-admin")
    first_app, first_group, _first_permission = _app_with_catalog("handover-onboard-a")
    second_app, second_group, _second_permission = _app_with_catalog("handover-onboard-b")
    template = OnboardingTemplate.objects.create(name="多应用入职模板")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=first_app,
        authorization_group=first_group,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=second_app,
        authorization_group=second_group,
    )
    newcomer = UserMirror.objects.create(authentik_user_id="handover-onboard-newcomer")
    real_merge = lifecycle_services._merge_into_current_grant  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
    merge_count = 0

    def fail_second_grant(
        *,
        user: UserMirror,
        app: App,
        groups: list[AuthorizationGroupGrantInput],
        direct_grants: list[ScopedDirectGrantInput],
        actor_id: str,
    ) -> AccessGrant:
        nonlocal merge_count
        merge_count += 1
        if merge_count == SECOND_UPDATE_CALL:
            raise RuntimeError(SECOND_GRANT_WRITE_ERROR)
        return real_merge(
            user=user,
            app=app,
            groups=groups,
            direct_grants=direct_grants,
            actor_id=actor_id,
        )

    monkeypatch.setattr(lifecycle_services, "_merge_into_current_grant", fail_second_grant)

    response = client.post(
        "/console/api/v1/lifecycle/onboard",
        data=dumps(
            {
                "user_id": newcomer.authentik_user_id,
                "template_id": template.id,
            },
        ),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert not AccessGrant.objects.filter(user=newcomer).exists()


def test_confirmed_transfer_diff_is_idempotent_and_conflicts_on_other_payload() -> None:
    client = _logged_in_superuser("handover-confirm-diff-admin")
    app, group, _permission = _app_with_catalog("handover-confirm-diff")
    added_permission = Permission.objects.create(
        app=app,
        key="order.view",
        name="订单查看",
        supported_scopes=["GLOBAL"],
    )
    subject = UserMirror.objects.create(authentik_user_id="handover-confirm-diff-subject")
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
        ),
    )
    task, _created = lifecycle_services.ensure_handover_task(
        subject=subject,
        kind="transfer",
        created_by="handover-confirm-diff-admin",
    )
    template = OnboardingTemplate.objects.create(name="差异确认模板")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=group,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        permission=added_permission,
        scope_key="GLOBAL",
    )
    build_response = client.post(
        f"{TASKS_URL}/{task.id}/grant-diff",
        data=dumps({"template_id": template.id}),
        content_type="application/json",
    )
    plan = TransferPlan.objects.get(task=task)
    add_diff = plan.grant_diff.get("add")
    assert isinstance(add_diff, list)
    add_keys: list[str] = []
    for entry in add_diff:
        assert isinstance(entry, dict)
        key = entry.get("key")
        assert isinstance(key, str)
        add_keys.append(key)
    payload = {"revoke_keys": [], "add_keys": add_keys}

    first_response = client.post(
        f"{TASKS_URL}/{task.id}/grant-diff/confirm",
        data=dumps(payload),
        content_type="application/json",
    )
    grant_count_after_first = AccessGrant.objects.filter(user=subject, app=app).count()
    same_response = client.post(
        f"{TASKS_URL}/{task.id}/grant-diff/confirm",
        data=dumps(payload),
        content_type="application/json",
    )
    conflicting_response = client.post(
        f"{TASKS_URL}/{task.id}/grant-diff/confirm",
        data=dumps({"revoke_keys": [], "add_keys": []}),
        content_type="application/json",
    )

    assert build_response.status_code == HTTPStatus.OK
    assert first_response.status_code == HTTPStatus.OK
    assert same_response.status_code == HTTPStatus.OK
    assert AccessGrant.objects.filter(user=subject, app=app).count() == grant_count_after_first
    assert conflicting_response.status_code == HTTPStatus.CONFLICT


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _app_with_catalog(app_key: str) -> tuple[App, AuthorizationGroup, Permission]:
    app = App.objects.create(app_key=app_key, name=app_key)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="member",
        kind="role",
        name="成员",
    )
    permission = Permission.objects.create(
        app=app,
        key="resource.view",
        name="资源查看",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    return app, group, permission
