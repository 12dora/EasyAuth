"""列表排序的关联表达式; 通过工厂延迟构建, 避免无关排序增加查询成本。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import (
    CharField,
    Count,
    DateTimeField,
    Exists,
    Min,
    OuterRef,
    Subquery,
)
from django.db.models.functions import Cast, Coalesce, Least

from easyauth.access_requests.models import AccessRequestApprover, AccessRequestGroup
from easyauth.accounts.models import UserMirror
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrantGroup, AccessGrantPermission

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models.expressions import Combinable


def first_grant_group() -> Combinable:
    return Subquery(
        AccessGrantGroup.objects.filter(grant_id=OuterRef("pk"))
        .order_by("authorization_group__name", "pk")
        .values("authorization_group__name")[:1]
    )


def first_request_group() -> Combinable:
    return Subquery(
        AccessRequestGroup.objects.filter(access_request_id=OuterRef("pk"))
        .order_by("authorization_group__name", "pk")
        .values("authorization_group__name")[:1]
    )


def first_approver() -> Combinable:
    current = Subquery(
        AccessRequestApprover.objects.filter(access_request_id=OuterRef("pk"))
        .order_by("approver__name", "pk")
        .values("approver__name")[:1]
    )
    decided = Subquery(
        UserMirror.objects.filter(authentik_user_id=OuterRef("decided_by")).values("name")[:1]
    )
    return Coalesce(current, decided)


def direct_permission_count() -> Combinable:
    return Count("grant_permissions", distinct=True)


def grant_expiration() -> Combinable:
    groups = Subquery(
        AccessGrantGroup.objects.filter(grant_id=OuterRef("pk"))
        .order_by()
        .values("grant_id")
        .annotate(minimum=Min("expires_at"))
        .values("minimum")[:1],
        output_field=DateTimeField(),
    )
    permissions = Subquery(
        AccessGrantPermission.objects.filter(grant_id=OuterRef("pk"))
        .order_by()
        .values("grant_id")
        .annotate(minimum=Min("expires_at"))
        .values("minimum")[:1],
        output_field=DateTimeField(),
    )
    # SQLite 的 Least 遇 NULL 返回 NULL, PostgreSQL 忽略 NULL; 统一取存在的最早时间。
    return Coalesce(Least(groups, permissions), groups, permissions)


def grant_apply_failure() -> Combinable:
    return Exists(
        AuditLog.objects.filter(
            event_type="grant_apply_failed",
            target_type="access_request",
            target_id=Cast(OuterRef("pk"), CharField()),
        )
    )


GRANT_ORDERING_ANNOTATIONS: dict[str, Callable[[], Combinable]] = {
    "ordering_group": first_grant_group,
    "ordering_permission_count": direct_permission_count,
    "ordering_expires_at": grant_expiration,
}
REQUEST_ORDERING_ANNOTATIONS: dict[str, Callable[[], Combinable]] = {
    "ordering_group": first_request_group,
    "ordering_approver": first_approver,
    "ordering_failure": grant_apply_failure,
}
