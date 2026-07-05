from __future__ import annotations

import json
import re
from hashlib import sha256
from http import HTTPStatus
from json import JSONDecodeError
from typing import TYPE_CHECKING, ClassVar, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.permission_template_handlers import CONFLICT_TEMPLATE_CODES
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
    parse_template_format,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.net import (
    BlockedHostError,
    InsecureUrlError,
    assert_public_host,
    require_secure_url,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

# 与 easyauth-app-sdk 的集成描述符契约保持一致(sdk/python/src/easyauth_app_sdk/descriptor.py)。
DESCRIPTOR_WELL_KNOWN_PATH: Final = "/.well-known/easyauth-app.json"
SUPPORTED_DESCRIPTOR_VERSION: Final = 1
DESCRIPTOR_MAX_BYTES: Final = 5 * 1024 * 1024
DESCRIPTOR_FETCH_TIMEOUT_SECONDS: Final = 10.0
APP_KEY_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

BASE_URL_INVALID_MESSAGE: Final = "base_url 必须是 http(s) URL。"
APP_KEY_INVALID_MESSAGE: Final = "app_key 格式无效。"


class AutoOnboardingError(Exception):
    def __init__(self, code: ErrorCode, message: str, status: HTTPStatus) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class AutoOnboardingPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    base_url: str = Field(max_length=512)
    app_key: str = Field(max_length=64)
    descriptor_token: str | None = Field(default=None, max_length=512)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        # 强制 https(仅本地开发允许 http://localhost); 明文 http 打内网会泄露 descriptor token。
        try:
            require_secure_url(normalized, allow_local_http=settings.DEBUG)
        except InsecureUrlError as error:
            raise ValueError(str(error)) from error
        return normalized

    @field_validator("app_key")
    @classmethod
    def validate_app_key(cls, value: str) -> str:
        normalized = value.strip()
        if APP_KEY_PATTERN.fullmatch(normalized) is None:
            raise ValueError(APP_KEY_INVALID_MESSAGE)
        return normalized

    @field_validator("descriptor_token")
    @classmethod
    def normalize_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def console_app_auto_onboarding(request: HttpRequest) -> JsonResponse:
    # 凭下游地址 + app_key 拉取集成描述符, 自动注册应用并导入权限 manifest。
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    try:
        payload = AutoOnboardingPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        result = _auto_onboard(payload=payload, actor_id=actor_id)
    except AutoOnboardingError as exc:
        return error_response(exc.code, exc.message, status=exc.status)
    _record_auto_onboarding(actor_id=actor_id, result=result)
    return json_response(result)


def _auto_onboard(*, payload: AutoOnboardingPayload, actor_id: str) -> dict[str, JsonValue]:
    descriptor = _fetch_descriptor(payload.base_url, payload.descriptor_token)
    manifest = _validated_manifest(descriptor, payload.app_key)
    # 固定的规范化序列化保证同内容重复接入可以按 content_hash 幂等判定。
    canonical_template = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)
    descriptor_app = descriptor["app"]
    with transaction.atomic():
        app, created = _ensure_app(payload.app_key, descriptor_app)
        latest = PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
        incoming_version = int(manifest["schema_version"])
        if latest is not None and incoming_version <= latest.version:
            if sha256(canonical_template.encode("utf-8")).hexdigest() == latest.content_hash:
                return _result(
                    app=app,
                    created=created,
                    already_up_to_date=True,
                    template_version=latest.version,
                )
            raise AutoOnboardingError(
                ErrorCode.CONFLICT,
                (
                    f"下游 manifest schema_version({incoming_version}) 未超过已导入版本"
                    f"({latest.version}) 且内容不一致, 请在下游递增版本后重试。"
                ),
                HTTPStatus.CONFLICT,
            )
        try:
            template = parse_permission_template(
                app_key=app.app_key,
                raw_template=canonical_template,
                template_format=parse_template_format("json"),
                imported_by=actor_id,
            )
            result = apply_permission_template(app=app, template=template)
        except PermissionTemplateImportError as exc:
            is_conflict = exc.code in CONFLICT_TEMPLATE_CODES
            raise AutoOnboardingError(
                ErrorCode.CONFLICT if is_conflict else ErrorCode.SEMANTIC_VALIDATION_ERROR,
                f"manifest 导入失败: {exc.message}",
                HTTPStatus.CONFLICT if is_conflict else HTTPStatus.UNPROCESSABLE_ENTITY,
            ) from exc
        return _result(
            app=app,
            created=created,
            already_up_to_date=False,
            template_version=result.template_version.version,
        )


def _ensure_app(app_key: str, descriptor_app: dict[str, JsonValue]) -> tuple[App, bool]:
    app = App.objects.filter(app_key=app_key).first()
    if app is not None:
        return app, False
    app = App(
        app_key=app_key,
        name=str(descriptor_app.get("name") or app_key),
        description=str(descriptor_app.get("description") or ""),
        is_active=True,
    )
    app.full_clean()
    app.save()
    return app, True


def _result(
    *,
    app: App,
    created: bool,
    already_up_to_date: bool,
    template_version: int,
) -> dict[str, JsonValue]:
    app.refresh_from_db()
    return {
        "app_key": app.app_key,
        "app_name": app.name,
        "created": created,
        "already_up_to_date": already_up_to_date,
        "template_version": template_version,
        "catalog_version": app.catalog_version,
    }


def _fetch_descriptor(base_url: str, descriptor_token: str | None) -> dict[str, JsonValue]:
    # 取回前在 fetch 边界(而非仅解析边界)校验主机, 关闭 DNS-rebinding 的 TOCTOU 窗口:
    # 拒绝解析到内网/环回/链路本地(含云元数据)的目标, 防止 SSRF。
    hostname = urlparse(base_url).hostname or ""
    try:
        assert_public_host(hostname, allow_local=settings.DEBUG)
    except BlockedHostError as error:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error
    headers = {"Accept": "application/json"}
    if descriptor_token:
        headers["Authorization"] = f"Bearer {descriptor_token}"
    request = Request(  # noqa: S310 - URL 由管理员显式提供且限定 http(s)。
        f"{base_url}{DESCRIPTOR_WELL_KNOWN_PATH}",
        headers=headers,
        method="GET",
    )
    try:
        with urlopen(request, timeout=DESCRIPTOR_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            raw_body = response.read(DESCRIPTOR_MAX_BYTES + 1)
    except HTTPError as error:
        status = (
            HTTPStatus.UNAUTHORIZED
            if error.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
            else HTTPStatus.BAD_GATEWAY
        )
        raise AutoOnboardingError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"拉取集成描述符失败: 下游返回 HTTP {error.code}。",
            status,
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise AutoOnboardingError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"无法连接下游应用: {getattr(error, 'reason', error)}",
            HTTPStatus.BAD_GATEWAY,
        ) from error
    if len(raw_body) > DESCRIPTOR_MAX_BYTES:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "集成描述符超过大小限制。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError) as error:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "集成描述符不是有效 JSON。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from error
    if not isinstance(parsed, dict):
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "集成描述符必须是 JSON object。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return parsed


def _validated_manifest(
    descriptor: dict[str, JsonValue],
    expected_app_key: str,
) -> dict[str, JsonValue]:
    if descriptor.get("descriptor_version") != SUPPORTED_DESCRIPTOR_VERSION:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            f"不支持的 descriptor_version: {descriptor.get('descriptor_version')!r}。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    descriptor_app = descriptor.get("app")
    if not isinstance(descriptor_app, dict) or descriptor_app.get("app_key") != expected_app_key:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "描述符 app_key 与请求不一致。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    manifest = descriptor.get("manifest")
    if not isinstance(manifest, dict):
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "描述符缺少 manifest。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    manifest_app = manifest.get("app")
    if not isinstance(manifest_app, dict) or manifest_app.get("app_key") != expected_app_key:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "manifest.app.app_key 与请求不一致。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    schema_version = manifest.get("schema_version")
    version_invalid = (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    )
    if version_invalid:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "manifest.schema_version 必须是 >=1 的整数。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return manifest


def _record_auto_onboarding(*, actor_id: str, result: dict[str, JsonValue]) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="app_auto_onboarded",
            target_type="app",
            target_id=str(result["app_key"]),
            metadata={
                "created": result["created"],
                "already_up_to_date": result["already_up_to_date"],
                "template_version": result["template_version"],
                "catalog_version": result["catalog_version"],
            },
        ),
    )
