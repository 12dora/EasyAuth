from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import pytest
from django.db.models.signals import post_save

from easyauth.applications.models import App, AppNotificationChannel

if TYPE_CHECKING:
    from collections.abc import Iterator


class _Signal(Protocol):
    def connect(self, receiver: object, *, sender: object, weak: bool = True) -> None: ...
    def disconnect(self, receiver: object, *, sender: object) -> bool | None: ...


@pytest.fixture(autouse=True)
def notification_channel_for_apps(db: None) -> Iterator[None]:
    _ = db

    def create_channel(*, instance: App, created: bool, **_kwargs: object) -> None:
        if not created:
            return
        _ = AppNotificationChannel.objects.create(
            app=instance,
            name="测试通知通道",
            dingtalk_app_key=f"key-{instance.app_key}",
            dingtalk_app_secret="test-secret",  # noqa: S106 - 测试专用固定值。
            agent_id="1001",
            version=1,
            is_active=True,
            created_by="pytest",
        )

    signal = cast("_Signal", cast("object", post_save))
    signal.connect(create_channel, sender=App, weak=False)
    try:
        yield
    finally:
        _ = signal.disconnect(create_channel, sender=App)
