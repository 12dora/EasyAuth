from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.http import HttpRequest, HttpResponse, JsonResponse
from pydantic import ConfigDict, Field, ValidationError

from easyauth.accounts.department_tree import DepartmentTree, DepartmentTreeCycleError
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.department_grants_payloads import (
    build_policy_view_context,
    effective_policies,
    serialize_department_summary,
    serialize_department_tree,
    serialize_policy_item,
    sort_policies_for_department,
)
from easyauth.admin_console.grant_write_common import (
    AdminGrantLookupError,
    AdminGrantSemanticError,
    AdminGrantWritePayload,
    resolve_admin_grant_targets,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.grants.department_policies import (
    DepartmentPolicyImmutableError,
    DepartmentPolicyWrite,
    DirectoryCorp,
    DirectoryDataError,
    DirectoryNotSyncedError,
    MultipleDirectoryCorpsError,
    create_department_grant_policy,
    delete_department_grant_policy,
    load_corp_membership_index,
    resolve_single_directory_corp,
    update_department_grant_policy,
)
from easyauth.grants.models import DepartmentGrantPolicy

if TYPE_CHECKING:
    from easyauth.accounts.department_tree import DepartmentTree as LoadedTree
    from easyauth.grants.department_policies import CorpMembershipIndex

type DirectoryLoad = tuple[DirectoryCorp, LoadedTree, CorpMembershipIndex]
type DirectoryResult = DirectoryLoad | JsonResponse
type PolicyResult = DepartmentGrantPolicy | JsonResponse

DEPT_NOT_FOUND_MESSAGE = "部门不存在。"
POLICY_NOT_FOUND_MESSAGE = "组织授权策略不存在。"
POLICY_DEPT_GONE_MESSAGE = "该部门已不在组织架构中，无法修改；请删除后在新部门重新创建"  # noqa: RUF001
DIRECTORY_CYCLE_MESSAGE = "部门镜像存在循环引用,请先修复目录数据。"
SOURCE_MISMATCH_MESSAGE = "请求的组织来源与当前目录不一致。"
SOURCE_PAIR_MESSAGE = "source_slug 与 corp_id 必须同时提供。"
TREE_EMPTY_MESSAGE = "尚未同步钉钉组织架构。"


class DepartmentPolicyCreatePayload(AdminGrantWritePayload):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    source_slug: str = Field(min_length=1, max_length=128)
    corp_id: str = Field(min_length=1, max_length=128)


def console_departments_tree(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str():
            pass
    if request.method != "GET":
        return method_not_allowed_response()
    match _loaded_directory():
        case JsonResponse() as response:
            return response
        case tuple() as loaded:
            corp, tree, memberships = loaded
    return json_response(
        {"data": serialize_department_tree(corp=corp, tree=tree, memberships=memberships)},
    )


def console_department_grant_policies(request: HttpRequest, dept_id: str) -> JsonResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str() as actor_id:
            pass
    if request.method == "GET":
        return _list_policies(request, dept_id)
    if request.method == "POST":
        return _create_policy(request, dept_id=dept_id, actor_id=actor_id)
    return method_not_allowed_response()


def console_department_grant_policy(
    request: HttpRequest,
    policy_id: int,
) -> JsonResponse | HttpResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str() as actor_id:
            pass
    if request.method == "PUT":
        return _update_policy(request, policy_id=policy_id, actor_id=actor_id)
    if request.method == "DELETE":
        return _delete_policy(policy_id=policy_id, actor_id=actor_id)
    return method_not_allowed_response()


def _list_policies(request: HttpRequest, dept_id: str) -> JsonResponse:
    match _loaded_directory():
        case JsonResponse() as response:
            return response
        case tuple() as loaded:
            corp, tree, memberships = loaded
    match _matching_corp(request, corp):
        case JsonResponse() as response:
            return response
        case DirectoryCorp():
            pass
    if dept_id not in tree.nodes:
        return _not_found(DEPT_NOT_FOUND_MESSAGE, {"dept_id": dept_id})
    try:
        ancestors = tree.ancestors_or_self(dept_id)
    except DepartmentTreeCycleError:
        return _conflict(DIRECTORY_CYCLE_MESSAGE, "directory_cycle")
    policies = sort_policies_for_department(
        effective_policies(
            source_slug=corp.source_slug,
            corp_id=corp.corp_id,
            dept_ids=ancestors,
        ),
        tree=tree,
        dept_id=dept_id,
    )
    context = build_policy_view_context(
        tree=tree,
        viewing_dept_id=dept_id,
        memberships=memberships,
        policies=policies,
    )
    items: list[JsonValue] = [serialize_policy_item(policy, context) for policy in policies]
    return json_response(
        {
            "data": {
                "department": serialize_department_summary(
                    tree=tree,
                    dept_id=dept_id,
                    memberships=memberships,
                ),
                "items": items,
            },
        },
    )


def _create_policy(request: HttpRequest, *, dept_id: str, actor_id: str) -> JsonResponse:
    try:
        payload = DepartmentPolicyCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _payload_error(exc)
    match _loaded_directory():
        case JsonResponse() as response:
            return response
        case tuple() as loaded:
            corp, tree, memberships = loaded
    mismatch = _corp_mismatch(payload.source_slug, payload.corp_id, corp)
    if mismatch is not None:
        return mismatch
    if dept_id not in tree.nodes:
        return _not_found(DEPT_NOT_FOUND_MESSAGE, {"dept_id": dept_id})
    try:
        targets = resolve_admin_grant_targets(payload)
        policy = create_department_grant_policy(
            DepartmentPolicyWrite(
                source_slug=corp.source_slug,
                corp_id=corp.corp_id,
                dept_id=dept_id,
                app=targets.app,
                authorization_groups=targets.authorization_groups,
                direct_grants=targets.direct_grants,
                grant_type=targets.grant_type,
                expires_at=targets.grant_expires_at,
                reason=targets.reason,
                actor_id=actor_id,
            ),
        )
    except (AdminGrantLookupError, AdminGrantSemanticError) as exc:
        return _write_error(exc)
    return json_response(
        {"data": _policy_item(policy, tree=tree, memberships=memberships)},
        status=HTTPStatus.CREATED,
    )


def _update_policy(request: HttpRequest, *, policy_id: int, actor_id: str) -> JsonResponse:
    try:
        payload = AdminGrantWritePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _payload_error(exc)
    match _policy_for_id(policy_id):
        case JsonResponse() as response:
            return response
        case DepartmentGrantPolicy() as policy:
            pass
    match _loaded_directory():
        case JsonResponse() as response:
            return response
        case tuple() as loaded:
            _corp, tree, memberships = loaded
    if policy.dept_id not in tree.nodes:
        return _conflict(POLICY_DEPT_GONE_MESSAGE, "department_removed")
    try:
        targets = resolve_admin_grant_targets(payload)
        updated = update_department_grant_policy(
            policy,
            DepartmentPolicyWrite(
                source_slug=policy.source_slug,
                corp_id=policy.corp_id,
                dept_id=policy.dept_id,
                app=targets.app,
                authorization_groups=targets.authorization_groups,
                direct_grants=targets.direct_grants,
                grant_type=targets.grant_type,
                expires_at=targets.grant_expires_at,
                reason=targets.reason,
                actor_id=actor_id,
            ),
        )
    except (AdminGrantLookupError, AdminGrantSemanticError, DepartmentPolicyImmutableError) as exc:
        return _write_error(exc)
    return json_response({"data": _policy_item(updated, tree=tree, memberships=memberships)})


def _delete_policy(*, policy_id: int, actor_id: str) -> HttpResponse | JsonResponse:
    match _policy_for_id(policy_id):
        case JsonResponse() as response:
            return response
        case DepartmentGrantPolicy() as policy:
            pass
    delete_department_grant_policy(policy=policy, actor_id=actor_id)
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


def _loaded_directory() -> DirectoryResult:
    try:
        corp = resolve_single_directory_corp()
        tree = DepartmentTree.load(source_slug=corp.source_slug, corp_id=corp.corp_id)
        if not tree.nodes or not tree.root_ids():
            return _conflict(TREE_EMPTY_MESSAGE, "directory_not_synced")
        memberships = load_corp_membership_index(
            source_slug=corp.source_slug,
            corp_id=corp.corp_id,
        )
    except DirectoryNotSyncedError as exc:
        return _conflict(str(exc), "directory_not_synced")
    except MultipleDirectoryCorpsError as exc:
        return _conflict(str(exc), "multiple_corps")
    except DirectoryDataError as exc:
        return _conflict(str(exc), "directory_data_invalid")
    except DepartmentTreeCycleError:
        return _conflict(DIRECTORY_CYCLE_MESSAGE, "directory_cycle")
    return corp, tree, memberships


def _matching_corp(request: HttpRequest, corp: DirectoryCorp) -> DirectoryCorp | JsonResponse:
    source_slug = request.GET.get("source_slug", "").strip()
    corp_id = request.GET.get("corp_id", "").strip()
    if source_slug == "" and corp_id == "":
        return corp
    if source_slug == "" or corp_id == "":
        return _semantic_error(AdminGrantSemanticError(SOURCE_PAIR_MESSAGE, (SOURCE_PAIR_MESSAGE,)))
    mismatch = _corp_mismatch(source_slug, corp_id, corp)
    return corp if mismatch is None else mismatch


def _corp_mismatch(source_slug: str, corp_id: str, corp: DirectoryCorp) -> JsonResponse | None:
    if source_slug != corp.source_slug or corp_id != corp.corp_id:
        return _semantic_error(
            AdminGrantSemanticError(SOURCE_MISMATCH_MESSAGE, (SOURCE_MISMATCH_MESSAGE,)),
        )
    return None


def _policy_item(
    policy: DepartmentGrantPolicy,
    *,
    tree: DepartmentTree,
    memberships: CorpMembershipIndex,
) -> dict[str, JsonValue]:
    match _policy_for_id(policy.id):
        case DepartmentGrantPolicy() as loaded:
            pass
        case JsonResponse():
            loaded = policy
    context = build_policy_view_context(
        tree=tree,
        viewing_dept_id=loaded.dept_id,
        memberships=memberships,
        policies=(loaded,),
    )
    return serialize_policy_item(loaded, context)


def _policy_for_id(policy_id: int) -> PolicyResult:
    policy = (
        DepartmentGrantPolicy.objects.select_related("app")
        .prefetch_related("policy_groups__authorization_group", "policy_permissions__permission")
        .filter(pk=policy_id)
        .first()
    )
    if policy is None:
        return _not_found(POLICY_NOT_FOUND_MESSAGE, {"id": policy_id})
    return policy


def _write_error(
    exc: AdminGrantLookupError | AdminGrantSemanticError | DepartmentPolicyImmutableError,
) -> JsonResponse:
    match exc:
        case AdminGrantLookupError():
            return error_response(exc.code, exc.message, exc.details, status=exc.status)
        case DepartmentPolicyImmutableError():
            return _semantic_error(AdminGrantSemanticError(str(exc), (str(exc),)))
        case AdminGrantSemanticError():
            return _semantic_error(exc)


def _payload_error(exc: ValidationError) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求参数无效。",
        {"errors": str(exc)},
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def _semantic_error(exc: AdminGrantSemanticError) -> JsonResponse:
    errors: list[JsonValue] = []
    errors.extend(exc.errors)
    return error_response(
        exc.code,
        exc.message,
        {"errors": errors},
        status=exc.status,
    )


def _not_found(message: str, details: dict[str, JsonValue]) -> JsonResponse:
    return error_response(ErrorCode.NOT_FOUND, message, details, status=HTTPStatus.NOT_FOUND)


def _conflict(message: str, reason: str) -> JsonResponse:
    return error_response(
        ErrorCode.CONFLICT,
        message,
        {"reason": reason},
        status=HTTPStatus.CONFLICT,
    )
