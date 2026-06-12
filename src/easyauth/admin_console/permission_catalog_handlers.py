from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from django.db import transaction

from easyauth.admin_console.configuration import (
    ConsoleMutationActor,
    RolePermissionMutation,
    set_role_permission,
)
from easyauth.admin_console.permission_catalog_data import (
    catalog_version,
    matrix_objects,
    matrix_objects_by_key,
)
from easyauth.applications.models import App, Permission, Role

if TYPE_CHECKING:
    from collections.abc import Callable

    from easyauth.admin_console.permission_matrix_payloads import MatrixSavePayload

MATRIX_OBJECTS_ERROR = "角色或权限不属于当前 App。"
MATRIX_PAYLOAD_ERROR = "矩阵提交参数无效。"


@final
class MatrixSaveConflictError(Exception):
    def __init__(self, current_version: str) -> None:
        super().__init__(current_version)
        self.current_version = current_version


@final
class MatrixSaveValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @override
    def __str__(self) -> str:
        return self.message


def save_permission_matrix(
    app: App,
    payload: MatrixSavePayload,
    actor_id: str,
    version_func: Callable[[App], str] = catalog_version,
) -> None:
    with transaction.atomic():
        locked_app = App.objects.select_for_update().get(id=app.id)
        current_version = version_func(locked_app)
        if _matrix_base_version(payload) != current_version:
            raise MatrixSaveConflictError(current_version=current_version)
        for role, permission, enabled in _matrix_mutations(locked_app, payload):
            set_role_permission(
                RolePermissionMutation(
                    app=locked_app,
                    role=role,
                    permission=permission,
                    enabled=enabled,
                    actor=ConsoleMutationActor(actor_id=actor_id),
                ),
            )


def _matrix_mutations(app: App, payload: MatrixSavePayload) -> list[tuple[Role, Permission, bool]]:
    mutations: list[tuple[Role, Permission, bool]] = []
    for assignment in payload.assignments:
        if objects := matrix_objects(
            app,
            role_id=assignment.role_id,
            permission_id=assignment.permission_id,
        ):
            mutations.append((*objects, assignment.enabled))
            continue
        message = MATRIX_OBJECTS_ERROR
        raise MatrixSaveValidationError(message)
    for assignment in payload.add:
        if objects := matrix_objects_by_key(
            app,
            role_key=assignment.role_key,
            permission_key=assignment.permission_key,
        ):
            mutations.append((*objects, True))
            continue
        message = MATRIX_OBJECTS_ERROR
        raise MatrixSaveValidationError(message)
    for assignment in payload.remove:
        if objects := matrix_objects_by_key(
            app,
            role_key=assignment.role_key,
            permission_key=assignment.permission_key,
        ):
            mutations.append((*objects, False))
            continue
        message = MATRIX_OBJECTS_ERROR
        raise MatrixSaveValidationError(message)
    return mutations


def _matrix_base_version(payload: MatrixSavePayload) -> str:
    if payload.base_version is not None:
        return payload.base_version
    if payload.version is not None:
        return payload.version
    message = MATRIX_PAYLOAD_ERROR
    raise MatrixSaveValidationError(message)
