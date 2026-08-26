from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.api_responses import method_not_allowed_response
from easyauth.admin_console.apps_api_payloads import CONFIGURATION_ISSUE_TARGET_TYPES
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    Page,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.admin_console.permission_template_api_data import template_version_item
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.ordering import parse_ordering
from easyauth.api.pagination import pagination_item
from easyauth.applications.configuration import (
    ConfigurationIssue,
    ConfigurationReadiness,
    configuration_readiness_for_app,
    configuration_readiness_statuses_for_apps,
)
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    AuthorizationGroup,
    OAuthClientBinding,
    Permission,
    PermissionTemplateVersion,
)
from easyauth.applications.ownership import (
    ConsoleActor,
    apps_visible_to_actor_queryset,
    can_manage_app,
    can_view_app,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet

type VisibleAppResult = App | JsonResponse

CONSOLE_APP_ORDERING: Final[dict[str, str]] = {
    "app_key": "app_key",
    "name": "name",
    "status": "is_active",
    "updated_at": "updated_at",
}
CONSOLE_APP_DEFAULT_ORDER: Final[tuple[str, ...]] = ("app_key",)


def list_console_apps(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return method_not_allowed_response()

    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match parse_ordering(request, CONSOLE_APP_ORDERING, CONSOLE_APP_DEFAULT_ORDER):
        case JsonResponse() as response:
            return response
        case tuple() as ordering:
            pass
    try:
        page = paginate_queryset(
            _filter_apps(_visible_apps_queryset(actor), request).order_by(*ordering),
            request.GET,
        )
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)
    return _items_response(_listed_app_items(actor, page.items), page)


def get_console_app_detail(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "GET":
        return method_not_allowed_response()

    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match visible_app(actor, app_key):
        case App() as app:
            return _json_response({"app": app_detail_item(actor, app)})
        case JsonResponse() as response:
            return response


def get_console_app_configuration_status(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "GET":
        return method_not_allowed_response()
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match visible_app(actor, app_key):
        case App() as app:
            readiness = configuration_readiness_for_app(app)
            issues: list[JsonValue] = []
            issues.extend(_configuration_issue_item(issue) for issue in readiness.issues)
            payload: dict[str, JsonValue] = {
                "app_key": app.app_key,
                "status": readiness.status,
                # 统一列表键为 canonical data(与 api_payloads.list_payload 一致), 不再用 items。
                "data": issues,
            }
            return _json_response(payload)
        case JsonResponse() as response:
            return response


def visible_app(actor: ConsoleActor, app_key: str) -> VisibleAppResult:
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return app


def app_detail_item(actor: ConsoleActor, app: App) -> dict[str, JsonValue]:
    # configuration_status 与 configuration_summary 共用一次 readiness, 避免重复扫配置。
    readiness = configuration_readiness_for_app(app)
    item = _app_item(actor, app, readiness.status)
    item["developers"] = _app_member_ids(app, "developer")
    item["authorization_group_count"] = AuthorizationGroup.objects.filter(app=app).count()
    item["permission_count"] = Permission.objects.filter(app=app).count()
    item["active_credential_count"] = _active_credential_count(app)
    item["latest_template_version"] = _latest_template_version_item(app)
    item["configuration_summary"] = _configuration_summary(readiness)
    return item


def _listed_app_items(
    actor: ConsoleActor,
    apps: tuple[App, ...],
) -> tuple[dict[str, JsonValue], ...]:
    readiness_statuses = configuration_readiness_statuses_for_apps(apps)
    # 列表只展示 owner; 一次查出可见集合, 再交给 item presenter, 避免按 App 打 membership。
    owner_ids_by_app_id = _member_ids_by_app_id(apps, "owner")
    return tuple(
        _app_item(
            actor,
            app,
            readiness_statuses.get(app.id),
            owner_ids=owner_ids_by_app_id.get(app.id, []),
        )
        for app in apps
    )


def _app_item(
    actor: ConsoleActor,
    app: App,
    readiness_status: str | None = None,
    *,
    owner_ids: list[JsonValue] | None = None,
) -> dict[str, JsonValue]:
    if readiness_status is None:
        readiness_status = configuration_readiness_for_app(app).status
    capabilities = _app_capabilities(actor, app)
    if owner_ids is None:
        owner_ids = _app_owner_ids(app)
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "is_active": app.is_active,
        "owners": owner_ids,
        "configuration_status": readiness_status,
        "updated_at": app.updated_at.isoformat(),
        "can_manage": capabilities["can_edit_basic_info"],
        "capabilities": capabilities,
    }


def _app_capabilities(actor: ConsoleActor, app: App) -> dict[str, JsonValue]:
    can_manage = can_manage_app(actor, app)
    return {
        "can_view": can_view_app(actor, app),
        "can_edit_basic_info": can_manage,
        "can_toggle_active": actor.is_superuser,
        "can_delete": actor.is_superuser,
        "can_manage_memberships": actor.is_superuser,
        "can_manage_catalog": can_manage,
        "can_manage_credentials": can_manage,
        "can_manage_connectors": actor.is_superuser,
        "can_manage_platform_capabilities": actor.is_superuser,
    }


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


def _member_ids_by_app_id(apps: tuple[App, ...], role: str) -> dict[int, list[JsonValue]]:
    app_ids = tuple(app.id for app in apps)
    member_ids_by_app_id: dict[int, list[JsonValue]] = {app_id: [] for app_id in app_ids}
    if not app_ids:
        return member_ids_by_app_id
    membership_rows = (
        AppMembership.objects.filter(
            app_id__in=app_ids,
            role=role,
            is_active=True,
        )
        .order_by("app_id", "user_id")
        .values_list("app_id", "user_id")
    )
    for raw_app_id, raw_user_id in cast("Iterable[tuple[object, object]]", membership_rows):
        app_id = cast("int", raw_app_id)
        member_ids_by_app_id.setdefault(app_id, []).append(cast("str", raw_user_id))
    return member_ids_by_app_id


def _visible_apps_queryset(actor: ConsoleActor) -> QuerySet[App]:
    return apps_visible_to_actor_queryset(actor)


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
            raise OperationFilterValidationError(
                key="status",
                value=status,
                message="status 必须为 active 或 inactive。",
            )


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
        paginated_list_payload(items=result, pagination=pagination_item(page)),
    )
