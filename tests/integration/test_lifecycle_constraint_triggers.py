"""跨表约束触发器 — 必须在真 PostgreSQL 上跑(01 §2.2)。"""

from __future__ import annotations

import pytest
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.models import (
    ACTION_STATUS_PENDING,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_SKIP,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    HandoverAppAction,
    HandoverAssetOverride,
    HandoverAssetType,
    HandoverTask,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="约束触发器只在 PostgreSQL lane 验证。",
    ),
]


def test_grant_receiver_offboard_trigger_rejects_reassign() -> None:
    subject = UserMirror.objects.create(authentik_user_id="trg-gr-sub")
    receiver = UserMirror.objects.create(authentik_user_id="trg-gr-recv")
    app = App.objects.create(app_key="trg-gr-app", name="trg")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_REASSIGN,
        subject_user=subject,
        created_by="admin",
        reason="trigger fixture",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PENDING,
    )
    action.grant_receiver = receiver
    with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
        action.save(update_fields=["grant_receiver", "updated_at"])


def test_override_releasable_trigger_rejects_release_when_not_releasable() -> None:
    subject = UserMirror.objects.create(authentik_user_id="trg-rel-sub")
    app = App.objects.create(app_key="trg-rel-app", name="trg-rel")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PENDING,
    )
    asset = HandoverAssetType.objects.create(
        action=action,
        generation=1,
        type_key="customer",
        label_snapshot="客户",
        count=1,
        releasable=False,
        default_action=ASSET_ACTION_SKIP,
    )
    with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
        _ = HandoverAssetOverride.objects.create(
            asset_type=asset,
            asset_id="c1",
            action=ASSET_ACTION_RELEASE,
        )


def test_override_releasable_trigger_rejects_parent_becoming_not_releasable() -> None:
    subject = UserMirror.objects.create(authentik_user_id="trg-parent-rel-sub")
    app = App.objects.create(app_key="trg-parent-rel-app", name="trg-parent-rel")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PENDING,
    )
    asset = HandoverAssetType.objects.create(
        action=action,
        generation=1,
        type_key="customer",
        label_snapshot="客户",
        count=1,
        releasable=True,
        default_action=ASSET_ACTION_SKIP,
    )
    _ = HandoverAssetOverride.objects.create(
        asset_type=asset,
        asset_id="c1",
        action=ASSET_ACTION_RELEASE,
    )

    with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
        _ = HandoverAssetType.objects.filter(pk=asset.pk).update(releasable=False)
