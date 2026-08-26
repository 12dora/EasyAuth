"""门户申请目录编排: 载入数据、解析审批人、序列化响应。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from easyauth.portal.request_catalog_approvers import (
    APPROVER_RESOLUTION_DEFAULT_POLICY,
    APPROVER_RESOLUTION_DIRECT_MANAGER_MISSING,
    APPROVER_RESOLUTION_RESOLVED_BY_DIRECT_MANAGER,
    MANAGED_USERS_SCOPE,
    resolve_request_catalog_approvers,
)
from easyauth.portal.request_catalog_data import (
    load_request_catalog_data,
    serialize_request_catalog,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.api.errors import JsonValue

__all__: Final = (
    "APPROVER_RESOLUTION_DEFAULT_POLICY",
    "APPROVER_RESOLUTION_DIRECT_MANAGER_MISSING",
    "APPROVER_RESOLUTION_RESOLVED_BY_DIRECT_MANAGER",
    "MANAGED_USERS_SCOPE",
    "load_request_catalog_data",
    "request_catalog_payload",
    "resolve_request_catalog_approvers",
    "serialize_request_catalog",
)


def request_catalog_payload(user: UserMirror) -> dict[str, JsonValue]:
    catalog = load_request_catalog_data()
    approvers = resolve_request_catalog_approvers(catalog, user)
    return serialize_request_catalog(catalog, approvers)
