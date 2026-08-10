"""契约 §4 主管链管辖权判定(reassign 专用, 禁止走 resolve_managed_users)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkUserOrgContext,
    UserMirror,
)

REASON_OUT_OF_SCOPE: Final = "out_of_managed_scope"
REASON_DIRECTORY_UNAVAILABLE: Final = "directory_unavailable"


@dataclass(frozen=True, slots=True)
class JurisdictionResult:
    allowed: bool
    reason: str = ""


def assert_manager_of(actor: UserMirror, subject: UserMirror) -> JurisdictionResult:
    """actor 是否在 subject 当前 manager_chain 上(契约 §4)。

    - 目录缺失 / stale / 链畸形 → directory_unavailable (503)
    - 目录健康但 actor 不在链上 → out_of_managed_scope (403)
    """
    if actor.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return JurisdictionResult(allowed=False, reason=REASON_OUT_OF_SCOPE)
    if subject.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return JurisdictionResult(allowed=False, reason=REASON_OUT_OF_SCOPE)
    if actor.status != USER_STATUS_ACTIVE or subject.status != USER_STATUS_ACTIVE:
        return JurisdictionResult(allowed=False, reason=REASON_OUT_OF_SCOPE)
    if int(actor.pk) == int(subject.pk):  # type: ignore[arg-type]
        return JurisdictionResult(allowed=False, reason=REASON_OUT_OF_SCOPE)
    if (
        not subject.dingtalk_source_slug
        or not subject.dingtalk_corp_id
        or not subject.dingtalk_userid
    ):
        return JurisdictionResult(allowed=False, reason=REASON_DIRECTORY_UNAVAILABLE)
    if (
        not actor.dingtalk_source_slug
        or not actor.dingtalk_corp_id
        or not actor.dingtalk_userid
    ):
        return JurisdictionResult(allowed=False, reason=REASON_DIRECTORY_UNAVAILABLE)
    # 必须同 (source, corp)
    if (
        actor.dingtalk_source_slug != subject.dingtalk_source_slug
        or actor.dingtalk_corp_id != subject.dingtalk_corp_id
    ):
        return JurisdictionResult(allowed=False, reason=REASON_OUT_OF_SCOPE)

    context = DingTalkUserOrgContext.objects.filter(
        source_slug=subject.dingtalk_source_slug,
        corp_id=subject.dingtalk_corp_id,
        user_id=subject.dingtalk_userid,
    ).first()
    if context is None or context.stale:
        return JurisdictionResult(allowed=False, reason=REASON_DIRECTORY_UNAVAILABLE)
    chain = context.manager_chain
    if not isinstance(chain, list):
        return JurisdictionResult(allowed=False, reason=REASON_DIRECTORY_UNAVAILABLE)

    actor_dtuid = actor.dingtalk_userid
    for entry in chain:
        if not isinstance(entry, dict):
            return JurisdictionResult(allowed=False, reason=REASON_DIRECTORY_UNAVAILABLE)
        manager_userid = entry.get("user_id")
        if not isinstance(manager_userid, str) or not manager_userid:
            return JurisdictionResult(allowed=False, reason=REASON_DIRECTORY_UNAVAILABLE)
        if manager_userid == actor_dtuid:
            return JurisdictionResult(allowed=True)
    return JurisdictionResult(allowed=False, reason=REASON_OUT_OF_SCOPE)


def list_reassign_subject_candidates(
    actor: UserMirror,
    *,
    q: str = "",
    limit: int = 50,
) -> list[UserMirror] | str:
    """purpose=reassign_subject 候选: 我的 dingtalk_userid 在其 manager_chain 上。

    返回 list 或 reason 字符串(directory_unavailable)。
    """
    if (
        not actor.dingtalk_source_slug
        or not actor.dingtalk_corp_id
        or not actor.dingtalk_userid
    ):
        return REASON_DIRECTORY_UNAVAILABLE

    # 扫描同企业 active 员工的组织上下文(非 stale)
    contexts = DingTalkUserOrgContext.objects.filter(
        source_slug=actor.dingtalk_source_slug,
        corp_id=actor.dingtalk_corp_id,
        stale=False,
    )
    matching_dtuids: list[str] = []
    for ctx in contexts.iterator():
        chain = ctx.manager_chain
        if not isinstance(chain, list):
            continue
        for entry in chain:
            if not isinstance(entry, dict):
                break
            mid = entry.get("user_id")
            if not isinstance(mid, str) or not mid:
                break
            if mid == actor.dingtalk_userid:
                matching_dtuids.append(ctx.user_id)
                break

    if not matching_dtuids:
        return []

    qs = UserMirror.objects.filter(
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug=actor.dingtalk_source_slug,
        dingtalk_corp_id=actor.dingtalk_corp_id,
        dingtalk_userid__in=matching_dtuids,
    ).exclude(authentik_user_id=actor.authentik_user_id).exclude(
        authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX,
    )
    q_stripped = q.strip()
    if q_stripped:
        qs = qs.filter(name__icontains=q_stripped)
    return list(qs.order_by("name", "authentik_user_id")[:limit])


def list_receiver_candidates(
    actor: UserMirror,
    *,
    subject: UserMirror | None = None,
    q: str = "",
    limit: int = 50,
) -> list[UserMirror]:
    """purpose=receiver: active 且非本人、非本地管理员; 可选排除 subject。"""
    qs = UserMirror.objects.filter(status=USER_STATUS_ACTIVE).exclude(
        authentik_user_id=actor.authentik_user_id,
    ).exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
    if subject is not None:
        qs = qs.exclude(pk=subject.pk)
    q_stripped = q.strip()
    if q_stripped:
        qs = qs.filter(name__icontains=q_stripped)
    return list(qs.order_by("name", "authentik_user_id")[:limit])
