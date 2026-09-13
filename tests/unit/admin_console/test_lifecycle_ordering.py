from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUBJECT,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    HandoverAppAction,
    HandoverTask,
)
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

TASKS_URL: Final = "/console/api/v1/lifecycle/handover-tasks"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_handover_tasks_order_by_assignee_state() -> None:
    client = _admin("ord-handover-state-admin")
    manager_user = UserMirror.objects.create(authentik_user_id="ord-handover-manager", name="Mgr")
    subject_user = UserMirror.objects.create(authentik_user_id="ord-handover-self", name="Self")
    manager_task = _task("ord-handover-mgr-subj", ASSIGNEE_STATE_MANAGER, assignee=manager_user)
    subject_task = _task("ord-handover-self-subj", ASSIGNEE_STATE_SUBJECT, assignee=subject_user)
    pool_task = _task("ord-handover-pool-subj", ASSIGNEE_STATE_SUPERUSER_POOL)

    assert _ids(client, "assignee_state") == [manager_task.id, subject_task.id, pool_task.id]
    assert _ids(client, "-assignee_state") == [pool_task.id, subject_task.id, manager_task.id]


def test_handover_tasks_order_by_blocked_action_count() -> None:
    client = _admin("ord-handover-blocked-admin")
    none = _task("ord-handover-blocked-0", ASSIGNEE_STATE_SUPERUSER_POOL)
    one = _task("ord-handover-blocked-1", ASSIGNEE_STATE_SUPERUSER_POOL)
    two = _task("ord-handover-blocked-2", ASSIGNEE_STATE_SUPERUSER_POOL)
    _blocked_actions(one, count=1)
    _blocked_actions(two, count=2)
    _ = HandoverAppAction.objects.create(
        task=none,
        app=App.objects.create(app_key="ord-handover-pending-app", name="P"),
        status=ACTION_STATUS_PENDING,
    )

    assert _ids(client, "blocked") == [none.id, one.id, two.id]
    assert _ids(client, "-blocked") == [two.id, one.id, none.id]


def test_handover_tasks_reject_unknown_ordering() -> None:
    client = _admin("ord-handover-unknown-admin")
    response = client.get(TASKS_URL, {"ordering": "unknown"})
    _assert_unknown(response, "unknown")


def _task(
    subject_id: str,
    assignee_state: str,
    *,
    assignee: UserMirror | None = None,
) -> HandoverTask:
    subject = UserMirror.objects.create(authentik_user_id=subject_id)
    return HandoverTask.objects.create(
        kind="offboard",
        subject_user=subject,
        assignee=assignee,
        assignee_state=assignee_state,
    )


def _blocked_actions(task: HandoverTask, *, count: int) -> None:
    for index in range(count):
        app = App.objects.create(
            app_key=f"{task.subject_user.authentik_user_id}-app-{index}",
            name=f"App {index}",
        )
        _ = HandoverAppAction.objects.create(
            task=task,
            app=app,
            status=ACTION_STATUS_BLOCKED,
        )


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _ids(client: Client, ordering: str) -> list[int]:
    response = client.get(TASKS_URL, {"ordering": ordering, "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    ids: list[int] = []
    for item in data:
        assert isinstance(item, dict), payload
        task_id = item["id"]
        assert isinstance(task_id, int)
        ids.append(task_id)
    return ids


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
