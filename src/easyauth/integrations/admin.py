from __future__ import annotations

from typing import TYPE_CHECKING, final

from django.contrib import admin

from easyauth.integrations.models import DingTalkStreamEvent

if TYPE_CHECKING:

    class DingTalkStreamEventAdminBase(admin.ModelAdmin[DingTalkStreamEvent]):
        pass

else:

    class DingTalkStreamEventAdminBase(admin.ModelAdmin):
        pass


@admin.register(DingTalkStreamEvent)
@final
class DingTalkStreamEventAdmin(DingTalkStreamEventAdminBase):
    # 收件箱是事件事实记录, 只读呈现; 处理状态由 Celery 任务回写, 不允许人工改写事实。
    list_display = (
        "created_at",
        "event_type",
        "corp_id",
        "status",
        "processed_at",
    )
    list_filter = ("status", "event_type")
    search_fields = ("event_id", "event_type", "corp_id")
    readonly_fields = (
        "event_id",
        "event_type",
        "corp_id",
        "born_at",
        "data",
        "status",
        "result",
        "error",
        "processed_at",
        "created_at",
        "updated_at",
    )
