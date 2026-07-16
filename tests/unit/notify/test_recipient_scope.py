from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from easyauth.accounts.directory_references import build_dingtalk_user_ref
from easyauth.accounts.models import DingTalkUserMirror
from easyauth.api.directory_payloads import user_list_item
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_USER_AMBIGUOUS,
    NOTIFY_ERROR_USER_SCOPE_MISMATCH,
    NOTIFY_RAW_REF_MAX_CHARS,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_SCOPED_REF_V1_MAX_CHARS,
    NOTIFY_TEMPLATE_TEXT,
    NotifyRecipient,
)
from easyauth.notify.services import accept_notify_message, resolve_recipients

pytestmark = pytest.mark.django_db


def _directory_user(
    *,
    corp_id: str,
    user_id: str = "shared-user",
    source_slug: str = "dingtalk",
) -> DingTalkUserMirror:
    return DingTalkUserMirror.objects.create(
        source_slug=source_slug,
        corp_id=corp_id,
        user_id=user_id,
        name=user_id,
        status="active",
    )


def test_legacy_dingtalk_ref_is_rejected_when_user_is_ambiguous() -> None:
    _ = _directory_user(corp_id="corp-a")
    _ = _directory_user(corp_id="corp-b")

    recipient = resolve_recipients(["dt:shared-user"])[0]

    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipient.error_code == NOTIFY_ERROR_USER_AMBIGUOUS


def test_scoped_ref_resolves_exact_enterprise_user() -> None:
    _ = _directory_user(corp_id="corp-a")
    _ = _directory_user(corp_id="corp-b")
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
    _ = _directory_user(corp_id="corp-b", user_id="other-corp-user")
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


def test_same_userid_in_two_enterprises_persists_scoped_pending_and_rejection() -> None:
    app = App.objects.create(app_key="notify-cross-corp-same-user", name="Cross Corp")
    channel = AppNotificationChannel.objects.get(app=app, is_active=True)
    channel.directory_source_slug = "dingtalk"
    channel.corp_id = "corp-a"
    channel.save(update_fields=["directory_source_slug", "corp_id", "updated_at"])
    _ = _directory_user(corp_id="corp-a")
    _ = _directory_user(corp_id="corp-b")
    corp_a_ref = build_dingtalk_user_ref(
        source_slug="dingtalk",
        corp_id="corp-a",
        user_id="shared-user",
    )
    corp_b_ref = build_dingtalk_user_ref(
        source_slug="dingtalk",
        corp_id="corp-b",
        user_id="shared-user",
    )

    result = accept_notify_message(
        app=app,
        recipients=[corp_a_ref, corp_b_ref],
        template=NOTIFY_TEMPLATE_TEXT,
        content="scoped recipients",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )

    recipients = {
        row.dingtalk_corp_id: row for row in NotifyRecipient.objects.filter(message=result.message)
    }
    assert recipients["corp-a"].status == NOTIFY_RECIPIENT_STATUS_PENDING
    assert recipients["corp-b"].status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipients["corp-b"].error_code == NOTIFY_ERROR_USER_SCOPE_MISMATCH


def test_same_scoped_recipient_is_deduplicated_and_database_protected() -> None:
    app = App.objects.create(app_key="notify-scoped-duplicate", name="Scoped Duplicate")
    channel = AppNotificationChannel.objects.get(app=app, is_active=True)
    channel.directory_source_slug = "dingtalk"
    channel.corp_id = "corp-a"
    channel.save(update_fields=["directory_source_slug", "corp_id", "updated_at"])
    _ = _directory_user(corp_id="corp-a")
    reference = build_dingtalk_user_ref(
        source_slug="dingtalk",
        corp_id="corp-a",
        user_id="shared-user",
    )

    result = accept_notify_message(
        app=app,
        recipients=[reference, reference],
        template=NOTIFY_TEMPLATE_TEXT,
        content="deduplicated",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )

    assert result.recipient_total == 1
    assert NotifyRecipient.objects.filter(message=result.message).count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        _ = NotifyRecipient.objects.create(
            message=result.message,
            raw_ref=reference,
            dingtalk_source_slug="dingtalk",
            dingtalk_corp_id="corp-a",
            dingtalk_userid="shared-user",
        )


def test_legacy_unscoped_recipient_rows_remain_duplicate_protected() -> None:
    app = App.objects.create(app_key="notify-legacy-duplicate", name="Legacy Duplicate")
    channel = AppNotificationChannel.objects.get(app=app, is_active=True)
    channel.directory_source_slug = "dingtalk"
    channel.corp_id = "corp-a"
    channel.save(update_fields=["directory_source_slug", "corp_id", "updated_at"])
    _ = _directory_user(corp_id="corp-a")
    reference = build_dingtalk_user_ref(
        source_slug="dingtalk",
        corp_id="corp-a",
        user_id="shared-user",
    )
    result = accept_notify_message(
        app=app,
        recipients=[reference],
        template=NOTIFY_TEMPLATE_TEXT,
        content="legacy uniqueness",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    _ = NotifyRecipient.objects.create(
        message=result.message,
        raw_ref="dt:legacy-user",
        dingtalk_source_slug="",
        dingtalk_corp_id="legacy-corp",
        dingtalk_userid="legacy-user",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        _ = NotifyRecipient.objects.create(
            message=result.message,
            raw_ref="dt:legacy-user",
            dingtalk_source_slug="",
            dingtalk_corp_id="",
            dingtalk_userid="legacy-user",
        )


def test_maximum_v1_directory_payload_reference_is_accepted_and_preserved() -> None:
    component = "😀" * 128
    mirror = _directory_user(
        source_slug=component,
        corp_id=component,
        user_id=component,
    )
    payload = user_list_item(
        dingtalk_user=mirror,
        authentik_user_id=None,
        departments=[],
    )
    reference = payload["user_ref"]
    assert isinstance(reference, str)
    assert len(reference) == NOTIFY_SCOPED_REF_V1_MAX_CHARS
    assert len(reference) <= NOTIFY_RAW_REF_MAX_CHARS
    app = App.objects.create(app_key="notify-max-scoped-ref", name="Maximum Scoped Ref")
    channel = AppNotificationChannel.objects.get(app=app, is_active=True)
    channel.directory_source_slug = component
    channel.corp_id = component
    channel.save(update_fields=["directory_source_slug", "corp_id", "updated_at"])

    result = accept_notify_message(
        app=app,
        recipients=[reference],
        template=NOTIFY_TEMPLATE_TEXT,
        content="maximum canonical reference",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )

    recipient = NotifyRecipient.objects.get(message=result.message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_PENDING
    assert recipient.raw_ref == reference
