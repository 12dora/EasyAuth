from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from easyauth.accounts.authentik_provisioning import (
    ProvisionKind,
    ProvisionOutcome,
    forget_provision_miss,
    provision_user_from_authentik,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, DingTalkUserMirror, UserMirror
from easyauth.admin_console.grant_write_common import AdminGrantLookupError
from easyauth.api.errors import ErrorCode
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryConflictError,
    AuthentikDirectoryError,
)

if TYPE_CHECKING:
    from easyauth.admin_console.direct_grants_payloads import DirectoryUserRef
    from easyauth.integrations.authentik.directory_payloads import MaterializedDirectoryUser

USER_INACTIVE_MESSAGE: Final = "用户当前不是在职状态,无法授予权限。"
DIRECTORY_USER_NOT_FOUND_MESSAGE: Final = "钉钉通讯录中不存在该人员。"
DIRECTORY_USER_INACTIVE_MESSAGE: Final = "该人员在钉钉通讯录中不是在职状态。"
UNION_ID_MISSING_MESSAGE: Final = "该人员缺少钉钉 unionId,无法开通账号。"
AUTHENTIK_ACCOUNT_CONFLICT_MESSAGE: Final = "Authentik 中已有冲突账号,需管理员处理。"
MATERIALIZE_UNAVAILABLE_MESSAGE: Final = "Authentik 目录开通账号暂不可用。"
PROVISION_FAILED_MESSAGE: Final = "Authentik 账号已开通,但 EasyAuth 未能建档。"
DIRECTORY_SOURCE_MISMATCH_MESSAGE: Final = "钉钉目录源与当前 Authentik 配置不一致。"
UNKNOWN_CONFLICT_MESSAGE: Final = "Authentik 返回了无法识别的账号冲突。"
DIRECTORY_USER_MATERIALIZED_ACTION: Final = "directory_user_materialized"

_CONFLICT_MESSAGES: Final[dict[str, str]] = {
    "union_id_missing": UNION_ID_MISSING_MESSAGE,
    "username_conflict": AUTHENTIK_ACCOUNT_CONFLICT_MESSAGE,
    "binding_conflict": AUTHENTIK_ACCOUNT_CONFLICT_MESSAGE,
    "directory_user_inactive": DIRECTORY_USER_INACTIVE_MESSAGE,
}


def resolve_directory_user_for_grant(
    identity: DirectoryUserRef,
    *,
    actor_id: str,
) -> UserMirror:
    _ = _require_active_directory_person(identity)
    existing = _existing_user_mirror(identity)
    if existing is not None:
        return _require_active_user(existing)
    return _materialize_and_provision(identity, actor_id=actor_id)


def _require_active_directory_person(identity: DirectoryUserRef) -> DingTalkUserMirror:
    person = DingTalkUserMirror.objects.filter(
        source_slug=identity.source_slug,
        corp_id=identity.corp_id,
        user_id=identity.user_id,
    ).first()
    if person is None:
        raise AdminGrantLookupError(
            DIRECTORY_USER_NOT_FOUND_MESSAGE,
            {
                "source_slug": identity.source_slug,
                "corp_id": identity.corp_id,
                "user_id": identity.user_id,
            },
            HTTPStatus.NOT_FOUND,
            ErrorCode.NOT_FOUND,
        )
    if person.is_tombstone or person.status != USER_STATUS_ACTIVE:
        raise AdminGrantLookupError(
            DIRECTORY_USER_INACTIVE_MESSAGE,
            {
                "source_slug": identity.source_slug,
                "corp_id": identity.corp_id,
                "user_id": identity.user_id,
            },
            HTTPStatus.CONFLICT,
            ErrorCode.CONFLICT,
        )
    return person


def _existing_user_mirror(identity: DirectoryUserRef) -> UserMirror | None:
    return UserMirror.objects.filter(
        dingtalk_source_slug=identity.source_slug,
        dingtalk_corp_id=identity.corp_id,
        dingtalk_userid=identity.user_id,
    ).first()


def _materialize_and_provision(identity: DirectoryUserRef, *, actor_id: str) -> UserMirror:
    materialized = _materialize_authentik_user(identity)
    forget_provision_miss(materialized.uuid)
    outcome = provision_user_from_authentik(materialized.uuid)
    user = _user_from_provision(outcome)
    if materialized.created or outcome.kind is ProvisionKind.CREATED:
        _record_directory_user_materialized(
            actor_id=actor_id,
            authentik_user_id=user.authentik_user_id,
            identity=identity,
            created=materialized.created,
        )
    return _require_active_user(user)


def _materialize_authentik_user(identity: DirectoryUserRef) -> MaterializedDirectoryUser:
    client = AuthentikDirectoryClient.from_settings()
    if identity.source_slug != client.source_slug:
        raise AdminGrantLookupError(
            DIRECTORY_SOURCE_MISMATCH_MESSAGE,
            {"source_slug": identity.source_slug},
            HTTPStatus.CONFLICT,
            ErrorCode.CONFLICT,
        )
    try:
        return client.materialize_user(identity.corp_id, identity.user_id)
    except AuthentikDirectoryConflictError as error:
        raise _conflict_lookup_error(error.code) from error
    except AuthentikDirectoryError as error:
        raise AdminGrantLookupError(
            MATERIALIZE_UNAVAILABLE_MESSAGE,
            {},
            HTTPStatus.SERVICE_UNAVAILABLE,
            ErrorCode.DEPENDENCY_UNAVAILABLE,
        ) from error


def _user_from_provision(outcome: ProvisionOutcome) -> UserMirror:
    if outcome.kind in {ProvisionKind.CREATED, ProvisionKind.EXISTING}:
        if outcome.user is None:
            raise AdminGrantLookupError(
                PROVISION_FAILED_MESSAGE,
                {},
                HTTPStatus.BAD_GATEWAY,
                ErrorCode.DEPENDENCY_UNAVAILABLE,
            )
        return outcome.user
    if outcome.kind is ProvisionKind.UNAVAILABLE:
        raise AdminGrantLookupError(
            MATERIALIZE_UNAVAILABLE_MESSAGE,
            {},
            HTTPStatus.SERVICE_UNAVAILABLE,
            ErrorCode.DEPENDENCY_UNAVAILABLE,
        )
    raise AdminGrantLookupError(
        PROVISION_FAILED_MESSAGE,
        {},
        HTTPStatus.BAD_GATEWAY,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
    )


def _require_active_user(user: UserMirror) -> UserMirror:
    if user.status != USER_STATUS_ACTIVE:
        raise AdminGrantLookupError(
            USER_INACTIVE_MESSAGE,
            {"user_id": user.authentik_user_id},
            HTTPStatus.CONFLICT,
            ErrorCode.CONFLICT,
        )
    return user


def _conflict_lookup_error(code: str) -> AdminGrantLookupError:
    message = _CONFLICT_MESSAGES.get(code)
    if message is None:
        return AdminGrantLookupError(
            UNKNOWN_CONFLICT_MESSAGE,
            {"code": code},
            HTTPStatus.BAD_GATEWAY,
            ErrorCode.DEPENDENCY_UNAVAILABLE,
        )
    return AdminGrantLookupError(
        message,
        {"code": code},
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
    )


def _record_directory_user_materialized(
    *,
    actor_id: str,
    authentik_user_id: str,
    identity: DirectoryUserRef,
    created: bool,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action=DIRECTORY_USER_MATERIALIZED_ACTION,
            target_type="user",
            target_id=authentik_user_id,
            metadata={
                "source_slug": identity.source_slug,
                "corp_id": identity.corp_id,
                "user_id": identity.user_id,
                "created": created,
            },
        ),
    )
