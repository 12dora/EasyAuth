from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from easyauth.notify.models import NotifyMessage

if TYPE_CHECKING:
    from django.db.models import ForeignKey

    from easyauth.applications.models import AppNotificationChannel


class _ModelMeta(Protocol):
    def get_field(self, field_name: str) -> object: ...


def test_notify_message_channel_is_required() -> None:
    field = cast(
        "ForeignKey[AppNotificationChannel, AppNotificationChannel]",
        cast("_ModelMeta", cast("object", NotifyMessage._meta)).get_field("channel"),  # noqa: SLF001
    )
    assert field.null is False
    assert field.blank is False
