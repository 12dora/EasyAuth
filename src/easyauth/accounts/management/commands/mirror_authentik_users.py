from __future__ import annotations

from typing import final, override

from django.core.management.base import BaseCommand

from easyauth.accounts.authentik_provisioning import mirror_missing_authentik_users
from easyauth.integrations.authentik.admin_client import AuthentikAdminClient


@final
class Command(BaseCommand):
    help = "从 Authentik 活跃用户补齐缺失的 UserMirror, 不覆盖已有镜像。"

    @override
    def handle(self, *args: object, **options: object) -> None:
        result = mirror_missing_authentik_users(AuthentikAdminClient.from_settings())
        self.stdout.write(
            " ".join(
                (
                    f"scanned={result.scanned}",
                    f"created={result.created}",
                    f"skipped_no_directory_identity={result.skipped_no_directory_identity}",
                    f"skipped_existing={result.skipped_existing}",
                ),
            ),
        )
