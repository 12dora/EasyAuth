from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.admin_console.apps_api_payloads import (
    APP_KEY_INVALID_MESSAGE,
    APP_KEY_PATTERN,
    CONFIGURATION_ISSUE_TARGET_TYPES,
    NAME_BLANK_MESSAGE,
    AppCreatePayload,
    AppPatchPayload,
)
from easyauth.admin_console.apps_api_reads import (
    app_detail_item,
    get_console_app_configuration_status,
    get_console_app_detail,
    list_console_apps,
    visible_app,
)
from easyauth.admin_console.apps_api_writes import (
    create_app,
    delete_app,
    patch_app,
)

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse, JsonResponse

# 显式再导出, 保持原模块路径上的公开符号与 mocker.patch 接缝。
__all__ = [
    "APP_KEY_INVALID_MESSAGE",
    "APP_KEY_PATTERN",
    "CONFIGURATION_ISSUE_TARGET_TYPES",
    "NAME_BLANK_MESSAGE",
    "AppCreatePayload",
    "AppPatchPayload",
    "app_detail_item",
    "console_app_configuration_status",
    "console_app_detail",
    "console_apps",
    "create_app",
    "delete_app",
    "get_console_app_configuration_status",
    "get_console_app_detail",
    "list_console_apps",
    "patch_app",
    "visible_app",
]


def console_apps(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        return create_app(request)
    return list_console_apps(request)


def console_app_detail(request: HttpRequest, app_key: str) -> JsonResponse | HttpResponse:
    if request.method == "PATCH":
        return patch_app(request, app_key)
    if request.method == "DELETE":
        return delete_app(request, app_key)
    return get_console_app_detail(request, app_key)


def console_app_configuration_status(request: HttpRequest, app_key: str) -> JsonResponse:
    return get_console_app_configuration_status(request, app_key)
