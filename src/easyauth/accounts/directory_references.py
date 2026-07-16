from __future__ import annotations

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from typing import Final, Literal

from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror

DT_PREFIX: Final = "dt:"
DEPT_PREFIX: Final = "dept:"
SCOPED_REF_VERSION: Final = "v1"
SCOPED_REF_PART_COUNT: Final = 4
USER_IDENTIFIER_MISSING_MESSAGE: Final = "用户引用缺少标识符。"
DEPARTMENT_IDENTIFIER_MISSING_MESSAGE: Final = "部门引用缺少标识符。"
SCOPED_COMPONENTS_MISSING_MESSAGE: Final = "scoped directory reference components must be non-empty"
ReferenceKind = Literal["authentik", "dingtalk"]


class InvalidDirectoryReferenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AmbiguousDirectoryReferenceError(ValueError):
    reference: str
    candidate_refs: tuple[str, ...]
    reference_type: Literal["user", "department"]


@dataclass(frozen=True, slots=True)
class ParsedUserReference:
    kind: ReferenceKind
    identifier: str
    source_slug: str = ""
    corp_id: str = ""
    scoped: bool = False


@dataclass(frozen=True, slots=True)
class ParsedDepartmentReference:
    department_id: str
    source_slug: str = ""
    corp_id: str = ""
    scoped: bool = False


def build_dingtalk_user_ref(*, source_slug: str, corp_id: str, user_id: str) -> str:
    return _build_scoped_ref(DT_PREFIX, source_slug, corp_id, user_id)


def build_department_ref(*, source_slug: str, corp_id: str, department_id: str) -> str:
    return _build_scoped_ref(DEPT_PREFIX, source_slug, corp_id, department_id)


def parse_user_ref(user_ref: str) -> ParsedUserReference:
    if not user_ref.startswith(DT_PREFIX):
        return ParsedUserReference(kind="authentik", identifier=user_ref)
    remainder = user_ref.removeprefix(DT_PREFIX)
    if not remainder.startswith(f"{SCOPED_REF_VERSION}:"):
        return ParsedUserReference(kind="dingtalk", identifier=remainder)
    source_slug, corp_id, user_id = _parse_scoped_ref(remainder, reference_type="user")
    return ParsedUserReference(
        kind="dingtalk",
        identifier=user_id,
        source_slug=source_slug,
        corp_id=corp_id,
        scoped=True,
    )


def parse_department_ref(reference: str) -> ParsedDepartmentReference:
    if not reference.startswith(f"{DEPT_PREFIX}{SCOPED_REF_VERSION}:"):
        return ParsedDepartmentReference(department_id=reference)
    remainder = reference.removeprefix(DEPT_PREFIX)
    source_slug, corp_id, department_id = _parse_scoped_ref(
        remainder,
        reference_type="department",
    )
    return ParsedDepartmentReference(
        department_id=department_id,
        source_slug=source_slug,
        corp_id=corp_id,
        scoped=True,
    )


def resolve_directory_user(user_ref: str) -> DingTalkUserMirror | None:
    parsed = parse_user_ref(user_ref)
    if not parsed.identifier:
        raise InvalidDirectoryReferenceError(USER_IDENTIFIER_MISSING_MESSAGE)
    if parsed.kind == "authentik":
        user = UserMirror.objects.filter(authentik_user_id=parsed.identifier).first()
        if user is None or not user.dingtalk_userid:
            return None
        rows = list(
            DingTalkUserMirror.objects.filter(
                corp_id=user.dingtalk_corp_id,
                user_id=user.dingtalk_userid,
            ).order_by("source_slug", "corp_id", "user_id")[:2],
        )
        return _unique_user_or_raise(user_ref, rows)
    queryset = DingTalkUserMirror.objects.filter(user_id=parsed.identifier)
    if parsed.scoped:
        return queryset.filter(
            source_slug=parsed.source_slug,
            corp_id=parsed.corp_id,
        ).first()
    rows = list(queryset.order_by("source_slug", "corp_id", "user_id")[:2])
    return _unique_user_or_raise(user_ref, rows)


def resolve_department_scope(
    reference: str,
) -> tuple[str, str, str] | None:
    parsed = parse_department_ref(reference)
    if not parsed.department_id:
        raise InvalidDirectoryReferenceError(DEPARTMENT_IDENTIFIER_MISSING_MESSAGE)
    queryset = DingTalkDepartmentMirror.objects.filter(dept_id=parsed.department_id)
    if parsed.scoped:
        exists = queryset.filter(
            source_slug=parsed.source_slug,
            corp_id=parsed.corp_id,
        ).exists()
        return (
            (
                parsed.source_slug,
                parsed.corp_id,
                parsed.department_id,
            )
            if exists
            else None
        )
    rows = list(queryset.order_by("source_slug", "corp_id", "dept_id")[:2])
    if len(rows) > 1:
        raise AmbiguousDirectoryReferenceError(
            reference=reference,
            candidate_refs=tuple(
                build_department_ref(
                    source_slug=row.source_slug,
                    corp_id=row.corp_id,
                    department_id=row.dept_id,
                )
                for row in rows
            ),
            reference_type="department",
        )
    if not rows:
        return None
    row = rows[0]
    return row.source_slug, row.corp_id, row.dept_id


def resolve_user_mirror(user_ref: str) -> UserMirror | None:
    parsed = parse_user_ref(user_ref)
    if not parsed.identifier:
        raise InvalidDirectoryReferenceError(USER_IDENTIFIER_MISSING_MESSAGE)
    if parsed.kind == "authentik":
        return UserMirror.objects.filter(authentik_user_id=parsed.identifier).first()
    if parsed.scoped:
        # 新同步策略保留目录 tombstone, scoped ref 不应绕开 source scope 回退到 UserMirror。
        return None
    rows = list(
        UserMirror.objects.filter(dingtalk_userid=parsed.identifier).order_by(
            "dingtalk_corp_id",
            "authentik_user_id",
        )[:2],
    )
    if len(rows) > 1:
        candidate_refs = tuple(
            build_dingtalk_user_ref(
                source_slug=mirror.source_slug,
                corp_id=mirror.corp_id,
                user_id=mirror.user_id,
            )
            for row in rows
            for mirror in DingTalkUserMirror.objects.filter(
                corp_id=row.dingtalk_corp_id,
                user_id=row.dingtalk_userid,
            ).order_by("source_slug")[:1]
        )
        raise AmbiguousDirectoryReferenceError(
            reference=user_ref,
            candidate_refs=candidate_refs,
            reference_type="user",
        )
    return rows[0] if rows else None


def _unique_user_or_raise(
    reference: str,
    rows: list[DingTalkUserMirror],
) -> DingTalkUserMirror | None:
    if len(rows) > 1:
        raise AmbiguousDirectoryReferenceError(
            reference=reference,
            candidate_refs=tuple(
                build_dingtalk_user_ref(
                    source_slug=row.source_slug,
                    corp_id=row.corp_id,
                    user_id=row.user_id,
                )
                for row in rows
            ),
            reference_type="user",
        )
    return rows[0] if rows else None


def _build_scoped_ref(prefix: str, source_slug: str, corp_id: str, identifier: str) -> str:
    if not source_slug or not corp_id or not identifier:
        raise InvalidDirectoryReferenceError(SCOPED_COMPONENTS_MISSING_MESSAGE)
    return ":".join(
        (
            prefix.removesuffix(":"),
            SCOPED_REF_VERSION,
            _encode_component(source_slug),
            _encode_component(corp_id),
            _encode_component(identifier),
        ),
    )


def _parse_scoped_ref(remainder: str, *, reference_type: str) -> tuple[str, str, str]:
    parts = remainder.split(":")
    if len(parts) != SCOPED_REF_PART_COUNT or parts[0] != SCOPED_REF_VERSION:
        message = f"{reference_type} scoped 引用格式无效。"
        raise InvalidDirectoryReferenceError(message)
    try:
        components = tuple(_decode_component(part) for part in parts[1:])
    except (Base64Error, UnicodeDecodeError) as error:
        message = f"{reference_type} scoped 引用编码无效。"
        raise InvalidDirectoryReferenceError(message) from error
    if any(not component for component in components):
        message = f"{reference_type} scoped 引用字段不能为空。"
        raise InvalidDirectoryReferenceError(message)
    return components[0], components[1], components[2]


def _encode_component(value: str) -> str:
    return urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode_component(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return b64decode(f"{value}{padding}", altchars=b"-_", validate=True).decode()
