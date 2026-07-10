from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import JsonValue
from easyauth.applications.models import App
from easyauth.lifecycle.models import HandoverAppAction, HandoverTask
from easyauth.lifecycle.services import HandoverConflictError, update_action_receiver

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-lifecycle-handover"
TASKS_URL: Final = "/console/api/v1/lifecycle/handover-tasks"
SECOND_UPDATE_CALL: Final = 2
CONCURRENT_CONFLICT_MESSAGE: Final = "并发状态冲突。"
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


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
