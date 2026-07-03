from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from django.contrib import admin

from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from django.http import HttpRequest

    class AuditLogAdminBase(admin.ModelAdmin[AuditLog]):
        pass

else:

    class AuditLogAdminBase(admin.ModelAdmin):
        pass


@admin.register(AuditLog)
@final
class AuditLogAdmin(AuditLogAdminBase):
    list_display = (
        "created_at",
        "event_type",
        "actor_type",
        "actor_id",
        "target_type",
        "target_id",
    )
    readonly_fields = (
        "id",
        "actor_type",
        "actor_id",
        "event_type",
        "target_type",
        "target_id",
        "metadata",
        "created_at",
    )
    search_fields = (
        "actor_id",
        "event_type",
        "target_id",
    )
    list_filter = (
        "actor_type",
        "target_type",
        "event_type",
    )

    @override
    def has_change_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

    @override
    def has_delete_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        # 模型是只追加的; 返回 True 会在列表页暴露必定 500 的批量删除动作。
        _ = request, obj
        return False
