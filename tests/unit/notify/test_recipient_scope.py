from __future__ import annotations

import pytest

from easyauth.accounts.directory_references import build_dingtalk_user_ref
from easyauth.accounts.models import DingTalkUserMirror
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_USER_AMBIGUOUS,
    NOTIFY_ERROR_USER_SCOPE_MISMATCH,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_TEMPLATE_TEXT,
    NotifyRecipient,
)
from easyauth.notify.services import accept_notify_message, resolve_recipients

pytestmark = pytest.mark.django_db


def _directory_user(*, corp_id: str, user_id: str = "shared-user") -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id=corp_id,
        user_id=user_id,
        name=user_id,
        status="active",
    )


def test_legacy_dingtalk_ref_is_rejected_when_user_is_ambiguous() -> None:
    _directory_user(corp_id="corp-a")
    _directory_user(corp_id="corp-b")

    recipient = resolve_recipients(["dt:shared-user"])[0]

    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipient.error_code == NOTIFY_ERROR_USER_AMBIGUOUS


def test_scoped_ref_resolves_exact_enterprise_user() -> None:
    _directory_user(corp_id="corp-a")
    _directory_user(corp_id="corp-b")
    reference = build_dingtalk_user_ref(
        source_slug="dingtalk",
        corp_id="corp-b",
        user_id="shared-user",
    )

    recipient = resolve_recipients([reference])[0]

    assert recipient.status == NOTIFY_RECIPIENT_STATUS_PENDING
    assert recipient.dingtalk_source_slug == "dingtalk"
    assert recipient.dingtalk_corp_id == "corp-b"


def test_recipient_outside_channel_scope_is_rejected() -> None:
    app = App.objects.create(app_key="notify-scope-mismatch", name="Scope Mismatch")
    channel = AppNotificationChannel.objects.get(app=app, is_active=True)
    channel.directory_source_slug = "dingtalk"
    channel.corp_id = "corp-a"
    channel.save(update_fields=["directory_source_slug", "corp_id", "updated_at"])
    _directory_user(corp_id="corp-b", user_id="other-corp-user")
    reference = build_dingtalk_user_ref(
        source_slug="dingtalk",
        corp_id="corp-b",
        user_id="other-corp-user",
    )

    result = accept_notify_message(
        app=app,
        recipients=[reference],
        template=NOTIFY_TEMPLATE_TEXT,
        content="must not cross corp",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )

    recipient = NotifyRecipient.objects.get(message=result.message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipient.error_code == NOTIFY_ERROR_USER_SCOPE_MISMATCH
