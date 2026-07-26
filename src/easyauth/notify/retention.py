from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from easyauth.notify.contracts import DEFAULT_RETENTION_DAYS, NOTIFY_PRUNE_BATCH_SIZE
from easyauth.notify.models import NotifyMessage


def prune_messages() -> int:
    """按保留期分批删除历史消息(级联收件人)。返回删除的消息行数。"""
    retention_days = getattr(settings, "EASYAUTH_NOTIFY_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
    if (
        not isinstance(retention_days, int)
        or isinstance(retention_days, bool)
        or retention_days < 1
    ):
        retention_days = DEFAULT_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_messages = 0
    while True:
        batch_ids = list(
            NotifyMessage.objects.filter(created_at__lt=cutoff)
            .order_by("created_at")
            .values_list("id", flat=True)[:NOTIFY_PRUNE_BATCH_SIZE],
        )
        if not batch_ids:
            break
        deleted, _ = NotifyMessage.objects.filter(id__in=batch_ids).delete()
        # delete() 计数含级联 recipients; 消息数按 batch 计。
        deleted_messages += len(batch_ids)
        if deleted == 0:
            break
    return deleted_messages
