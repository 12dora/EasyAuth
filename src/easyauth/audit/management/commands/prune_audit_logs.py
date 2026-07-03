from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast, final, override

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from easyauth.audit.models import AuditLog, AuditLogQuerySet

if TYPE_CHECKING:
    from argparse import ArgumentParser


@final
class Command(BaseCommand):
    help = "按保留期清理审计日志; 这是审计表唯一合法的删除口径。"

    @override
    def add_arguments(self, parser: ArgumentParser) -> None:
        _ = parser.add_argument(
            "--keep-days",
            type=int,
            required=True,
            help="保留最近 N 天的审计日志, 删除更早的记录。",
        )

    @override
    def handle(self, *args: object, **options: object) -> None:
        keep_days = options.get("keep_days")
        if not isinstance(keep_days, int) or keep_days < 1:
            message = "--keep-days 必须是正整数。"
            raise CommandError(message)
        cutoff = timezone.now() - timedelta(days=keep_days)
        queryset = cast("AuditLogQuerySet", AuditLog.objects.all())
        deleted_count = queryset.purge_created_before(cutoff)
        self.stdout.write(f"已删除 {deleted_count} 条早于 {cutoff.isoformat()} 的审计日志。")
