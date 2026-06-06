from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.operation_filters import Page, paginate_queryset
from easyauth.admin_console.permission_template_api_data import template_version_item
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.configuration import (
    ConfigurationIssue,
    ConfigurationReadiness,
    configuration_readiness_for_app,
)
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    OAuthClientBinding,
    Permission,
    PermissionTemplateVersion,
    Role,
)
from easyauth.applications.ownership import (
    ConsoleActor,
    can_manage_app,
    can_view_app,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

type ConsoleAppsApiResult = ConsoleActor | JsonResponse
type VisibleAppResult = App | JsonResponse

CONFIGURATION_ISSUE_TARGET_TYPES: Final = {
    "app_inactive": "app",
    "active_role_missing": "app",
    "active_credential_missing": "app",
    "requestable_role_approval_rule_missing": "role",
    "requestable_role_permission_missing": "role",
    "permission_group_missing": "permission",
}


def console_apps(request: HttpRequest) -> JsonResponse:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    page = paginate_queryset(_filter_apps(_visible_apps_queryset(actor), request), request.GET)
    return _items_response(tuple(_app_item(app) for app in page.items), page)


def console_app_detail(request: HttpRequest, app_key: str) -> JsonResponse:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _visible_app(actor, app_key):
        case App() as app:
            return _json_response({"app": _app_detail_item(actor, app)})
        case JsonResponse() as response:
            return response


def console_app_configuration_status(request: HttpRequest, app_key: str) -> JsonResponse:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _visible_app(actor, app_key):
        case App() as app:
            readiness = configuration_readiness_for_app(app)
            issues: list[JsonValue] = []
            issues.extend(_configuration_issue_item(issue) for issue in readiness.issues)
            payload: dict[str, JsonValue] = {
                "app_key": app.app_key,
                "status": readiness.status,
                "issues": issues,
                "items": issues,
            }
            return _json_response(payload)
        case JsonResponse() as response:
            return response


def _actor_from_request(request: HttpRequest) -> ConsoleAppsApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def _visible_app(actor: ConsoleActor, app_key: str) -> VisibleAppResult:
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return app


def _app_item(app: App) -> dict[str, JsonValue]:
    readiness = configuration_readiness_for_app(app)
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "is_active": app.is_active,
        "owners": _app_owner_ids(app),
        "configuration_status": readiness.status,
        "updated_at": app.updated_at.isoformat(),
    }


def _app_detail_item(actor: ConsoleActor, app: App) -> dict[str, JsonValue]:
    item = _app_item(app)
    item["can_manage"] = can_manage_app(actor, app)
    item["developers"] = _app_member_ids(app, "developer")
    item["role_count"] = Role.objects.filter(app=app).count()
    item["permission_count"] = Permission.objects.filter(app=app).count()
    item["active_credential_count"] = _active_credential_count(app)
    item["latest_template_version"] = _latest_template_version_item(app)
    item["configuration_summary"] = _configuration_summary(
        configuration_readiness_for_app(app),
    )
    return item


def _configuration_issue_item(issue: ConfigurationIssue) -> dict[str, JsonValue]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "level": issue.severity,
        "message": issue.message,
        "subject": issue.subject,
        "target_type": CONFIGURATION_ISSUE_TARGET_TYPES.get(issue.code, "configuration_issue"),
        "target_id": issue.subject,
    }


def _app_owner_ids(app: App) -> list[JsonValue]:
    return _app_member_ids(app, "owner")


def _app_member_ids(app: App, role: str) -> list[JsonValue]:
    memberships = AppMembership.objects.filter(app=app, role=role, is_active=True).order_by(
        "user_id",
    )
    result: list[JsonValue] = []
    result.extend(memberships.values_list("user_id", flat=True))
    return result


def _visible_apps_queryset(actor: ConsoleActor) -> QuerySet[App]:
    if actor.is_superuser:
        return App.objects.order_by("app_key")

    app_ids = AppMembership.objects.filter(
        user_id=actor.user_id,
        role__in=("owner", "developer"),
        is_active=True,
    ).values_list("app_id", flat=True)
    return App.objects.filter(id__in=app_ids).order_by("app_key").distinct()


def _filter_apps(queryset: QuerySet[App], request: HttpRequest) -> QuerySet[App]:
    queryset = _filter_app_status(queryset, request.GET.get("status", ""))
    owner_user_id = request.GET.get("owner_user_id", "")
    if owner_user_id == "":
        return queryset
    return queryset.filter(
        memberships__user_id=owner_user_id,
        memberships__role="owner",
        memberships__is_active=True,
    ).distinct()


def _filter_app_status(queryset: QuerySet[App], status: str) -> QuerySet[App]:
    match status:
        case "active":
            return queryset.filter(is_active=True)
        case "inactive":
            return queryset.filter(is_active=False)
        case "":
            return queryset
        case _:
            return queryset


def _active_credential_count(app: App) -> int:
    static_count = AppCredential.objects.filter(app=app, is_active=True).count()
    oauth_count = OAuthClientBinding.objects.filter(app=app, is_active=True).count()
    return static_count + oauth_count


def _latest_template_version_item(app: App) -> JsonValue:
    template_version = (
        PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    )
    if template_version is None:
        return None
    return template_version_item(template_version)


def _configuration_summary(readiness: ConfigurationReadiness) -> dict[str, JsonValue]:
    return {
        "status": readiness.status,
        "issue_count": len(readiness.issues),
        "blocking_count": _issue_count(readiness, "blocking"),
        "warning_count": _issue_count(readiness, "warning"),
    }


def _issue_count(readiness: ConfigurationReadiness, severity: str) -> int:
    return sum(1 for issue in readiness.issues if issue.severity == severity)


def _items_response(
    items: tuple[dict[str, JsonValue], ...],
    page: Page[App],
) -> JsonResponse:
    result: list[JsonValue] = []
    result.extend(items)
    return _json_response(
        paginated_list_payload(items=result, pagination=_pagination_item(page)),
    )


def _pagination_item(page: Page[App]) -> dict[str, JsonValue]:
    return {
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
    }


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
