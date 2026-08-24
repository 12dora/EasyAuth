"""为全栈 Playwright 交接 E2E 播种: manager / subject / app / offboard task。

走真实 ``ensure_handover_task`` 入口建单, 不绕过 lifecycle 不变量。
仅在 ``DJANGO_DEBUG=1`` 下可用。
"""

from __future__ import annotations

import os
from typing import Final, cast, override

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.inputs import AuthorizationGroupGrantInput
from easyauth.grants.models import AccessGrant
from easyauth.grants.services import GrantMutationInput, GrantService
from easyauth.lifecycle.models import HANDOVER_KIND_OFFBOARD, HandoverAppAction, HandoverTask
from easyauth.lifecycle.offboarding import HandoverCreationSpec, ensure_handover_task
from easyauth.webhooks.models import AppWebhookConfig

SOURCE_SLUG = "e2e-src"
CORP_ID = "e2e-corp"
APP_KEY = "e2e-handover-app"
DEFAULT_MANAGER_USER = "manager"
DEFAULT_SUBJECT_USER = "e2e-subject"
DEFAULT_PEER_USER = "e2e-peer"
DEFAULT_DOWNSTREAM_PORT = "18010"
DEFAULT_SECRET = "whsec_e2e_handover"  # noqa: S105 - E2E 固定密钥, 非生产机密。
ASSET_TYPES: list[dict[str, object]] = [
    {
        "type": "document",
        "label": "文档",
        "detail_supported": True,
        "releasable": False,
    },
]
_DEBUG_REQUIRED_MESSAGE: Final = "seed_handover_e2e 仅允许在 DJANGO_DEBUG=1 下运行。"


class Command(BaseCommand):
    help: str = "播种全栈 E2E 交接场景(manager / subject / declared app / offboard task)。"

    @override
    def handle(self, *_args: str, **_options: object) -> None:
        if not cast("bool", settings.DEBUG):
            raise CommandError(_DEBUG_REQUIRED_MESSAGE)

        manager_username = (
            os.environ.get("EASYAUTH_E2E_MANAGER_USER", DEFAULT_MANAGER_USER).strip()
            or DEFAULT_MANAGER_USER
        )
        subject_username = (
            os.environ.get("EASYAUTH_E2E_SUBJECT_USER", DEFAULT_SUBJECT_USER).strip()
            or DEFAULT_SUBJECT_USER
        )
        downstream_port = (
            os.environ.get("EASYAUTH_E2E_DOWNSTREAM_PORT", DEFAULT_DOWNSTREAM_PORT).strip()
            or DEFAULT_DOWNSTREAM_PORT
        )
        secret = (
            os.environ.get("EASYAUTH_E2E_DOWNSTREAM_SECRET", DEFAULT_SECRET).strip()
            or DEFAULT_SECRET
        )
        handover_url = (
            f"http://127.0.0.1:{downstream_port}/api/v1/easyauth/lifecycle/handover"
        )

        with transaction.atomic():
            manager = self._ensure_user(
                authentik_user_id=manager_username,
                name=f"E2E Manager ({manager_username})",
                email=f"{manager_username}@e2e.easyauth.test",
                dingtalk_userid=f"dt-{manager_username}",
            )
            subject = self._ensure_user(
                authentik_user_id=subject_username,
                name=f"E2E Subject ({subject_username})",
                email=f"{subject_username}@e2e.easyauth.test",
                dingtalk_userid=f"dt-{subject_username}",
            )
            peer_username = (
                os.environ.get("EASYAUTH_E2E_PEER_USER", DEFAULT_PEER_USER).strip()
                or DEFAULT_PEER_USER
            )
            peer = self._ensure_user(
                authentik_user_id=peer_username,
                name=f"E2E Peer ({peer_username})",
                email=f"{peer_username}@e2e.easyauth.test",
                dingtalk_userid=f"dt-{peer_username}",
            )
            _ = DingTalkUserOrgContext.objects.update_or_create(
                source_slug=SOURCE_SLUG,
                corp_id=CORP_ID,
                user_id=subject.dingtalk_userid,
                defaults={
                    "manager_chain": [{"user_id": manager.dingtalk_userid}],
                    "stale": False,
                },
            )
            app = self._ensure_app(handover_url=handover_url, secret=secret)
            self._ensure_subject_grant(subject=subject, app=app)
            task, created = ensure_handover_task(
                subject=subject,
                kind=HANDOVER_KIND_OFFBOARD,
                created_by="seed_handover_e2e",
                spec=HandoverCreationSpec(
                    reason="全栈 E2E 交接试点",
                    app_keys=(app.app_key,),
                ),
            )
            # peer 仅作接收人候选; 确保 seed 路径引用到 peer 防止未使用
            _ = peer.authentik_user_id
            task = HandoverTask.objects.select_related("assignee", "subject_user").get(
                pk=task.id,
            )
            action_count = HandoverAppAction.objects.filter(task=task).count()

        self.stdout.write(
            self.style.SUCCESS(
                "".join(
                    (
                        "seed_handover_e2e ok: ",
                        f"manager={manager.authentik_user_id} ",
                        f"subject={subject.authentik_user_id} ",
                        f"app={app.app_key} ",
                        f"task={task.id} created={created} ",
                        "assignee=",
                        f"{task.assignee.authentik_user_id if task.assignee else None} ",
                        f"actions={action_count} ",
                        f"handover_url={handover_url}",
                    ),
                ),
            ),
        )

    def _ensure_user(
        self,
        *,
        authentik_user_id: str,
        name: str,
        email: str,
        dingtalk_userid: str,
    ) -> UserMirror:
        user, _created = UserMirror.objects.update_or_create(
            authentik_user_id=authentik_user_id,
            defaults={
                "name": name,
                "email": email,
                "status": USER_STATUS_ACTIVE,
                "dingtalk_source_slug": SOURCE_SLUG,
                "dingtalk_corp_id": CORP_ID,
                "dingtalk_userid": dingtalk_userid,
            },
        )
        return user

    def _ensure_app(self, *, handover_url: str, secret: str) -> App:
        app, _created = App.objects.update_or_create(
            app_key=APP_KEY,
            defaults={
                "name": "E2E Handover App",
                "is_active": True,
                "handover_capability": HANDOVER_CAPABILITY_DECLARED,
                "handover_asset_types": ASSET_TYPES,
            },
        )
        config, _cfg_created = AppWebhookConfig.objects.get_or_create(app=app)
        config.secret = secret
        config.handover_url = handover_url
        config.enabled = True
        config.save()
        # 目录供授权快照用
        scope, _ = AppScope.objects.get_or_create(
            app=app,
            key="GLOBAL",
            defaults={"name": "Global"},
        )
        group, _ = AuthorizationGroup.objects.get_or_create(
            app=app,
            key="member",
            defaults={"kind": "role", "name": "成员"},
        )
        permission, _ = Permission.objects.get_or_create(
            app=app,
            key="document.view",
            defaults={
                "name": "查看文档",
                "supported_scopes": [scope.key],
            },
        )
        _ = AuthorizationGroupGrant.objects.get_or_create(
            authorization_group=group,
            permission=permission,
            scope_key=scope.key,
        )
        return app

    def _ensure_subject_grant(self, *, subject: UserMirror, app: App) -> None:
        group = AuthorizationGroup.objects.get(app=app, key="member")
        existing = AccessGrant.objects.filter(
            user=subject,
            app=app,
            is_current=True,
            status="active",
        ).exists()
        if existing:
            return
        _ = GrantService.create_grant(
            GrantMutationInput(
                user=subject,
                app=app,
                authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            ),
        )
