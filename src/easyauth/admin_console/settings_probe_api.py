"""控制台设置页的三个「测试连接」端点。

三张集成卡片各自一个 POST 探针, 共用同一套约定:

* URL 形如 `/console/api/v1/settings/integrations/<target>/test`;
* 权限与设置页一致(`require_superuser`), 只接受 POST;
* 每次调用落一条审计, 元数据只含 ok / error_code / 耗时, **绝不**回显凭证;
* 按管理员 + 目标限流, 防止把测试按钮当成对上游的压测入口;
* 请求体是可选的「草稿」: 表单里尚未保存的值优先, 缺省(含留空的 secret)回落到落库值,
  因此探测的永远是"保存后真正会被使用的那组凭证"。

响应统一为 `{ok, latency_ms, error_code, error_message}`。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from time import monotonic
from typing import ClassVar, Final

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    require_method,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.api.errors import ErrorCode
from easyauth.applications.integration_settings import (
    INTEGRATION_SETTINGS_SINGLETON_ID,
    DingTalkCredentialTriple,
    IntegrationSettings,
    authentik_runtime_config,
    dingtalk_runtime_config,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.net import InsecureUrlError, require_secure_url
from easyauth.config.rate_limit import rate_limit_exceeded
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminClient,
    AuthentikAdminError,
    AuthentikAdminPermissionError,
)
from easyauth.integrations.dingtalk.api_client import DingTalkApiClient
from easyauth.integrations.dingtalk.errors import (
    DingTalkApiError,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
)

# 探测失败分型: 前端只展示 error_message, error_code 供审计与排障区分运维动作。
PROBE_ERROR_NOT_CONFIGURED: Final = "NOT_CONFIGURED"
PROBE_ERROR_INSECURE_BASE_URL: Final = "INSECURE_BASE_URL"
PROBE_ERROR_UNAUTHORIZED: Final = "UNAUTHORIZED"
PROBE_ERROR_REJECTED: Final = "REJECTED"
PROBE_ERROR_UNAVAILABLE: Final = "UNAVAILABLE"

PROBE_TARGET_AUTHENTIK: Final = "authentik"
PROBE_TARGET_DINGTALK: Final = "dingtalk"
PROBE_TARGET_DINGTALK_NOTIFY: Final = "dingtalk_notify"

PROBE_RATE_LIMIT_NAMESPACE: Final = "console-connectivity-test"
PROBE_RATE_LIMIT_MAX: Final = 30
PROBE_RATE_LIMIT_WINDOW_SECONDS: Final = 60

PROBE_THROTTLED_MESSAGE: Final = "连通性测试过于频繁, 请稍后再试。"
INVALID_PAYLOAD_MESSAGE: Final = "请求参数无效。"
AUTHENTIK_BASE_URL_MISSING_MESSAGE: Final = "未配置 Authentik Base URL。"
AUTHENTIK_API_TOKEN_MISSING_MESSAGE: Final = "未配置 Authentik API Token。"  # noqa: S105 - 提示文案, 非凭据.
AUTHENTIK_INSECURE_BASE_URL_MESSAGE: Final = (
    "Authentik Base URL 必须是 https(仅本机 localhost 允许 http), 拒绝明文传输管理 token。"
)
DINGTALK_CREDENTIALS_MISSING_MESSAGE: Final = "钉钉凭证不完整: AppKey 与 AppSecret 均不能为空。"


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    ok: bool
    error_code: str = ""
    error_message: str = ""


PROBE_OK: Final = ProbeOutcome(ok=True)


class AuthentikProbeDraft(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    authentik_base_url: str = Field(default="", max_length=512)
    authentik_api_token: str = Field(default="", max_length=512)

    @field_validator("authentik_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("authentik_api_token")
    @classmethod
    def normalize_api_token(cls, value: str) -> str:
        return value.strip()


class DingtalkAppProbeDraft(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    dingtalk_app_key: str = Field(default="", max_length=128)
    dingtalk_app_secret: str = Field(default="", max_length=512)
    dingtalk_agent_id: str = Field(default="", max_length=64)

    @field_validator("dingtalk_app_key", "dingtalk_app_secret", "dingtalk_agent_id")
    @classmethod
    def normalize_string(cls, value: str) -> str:
        return value.strip()


class DingtalkNotifyProbeDraft(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    dingtalk_notify_app_key: str = Field(default="", max_length=128)
    dingtalk_notify_app_secret: str = Field(default="", max_length=512)
    dingtalk_notify_agent_id: str = Field(default="", max_length=64)

    @field_validator(
        "dingtalk_notify_app_key",
        "dingtalk_notify_app_secret",
        "dingtalk_notify_agent_id",
    )
    @classmethod
    def normalize_string(cls, value: str) -> str:
        return value.strip()


def console_authentik_connectivity_test(request: HttpRequest) -> JsonResponse:
    """Authentik: 带 token 拉一页核心用户, 同时证明 Base URL 可达与 token 可用。"""
    guard = _guard(request, target=PROBE_TARGET_AUTHENTIK)
    if isinstance(guard, JsonResponse):
        return guard
    draft = _parse_draft(request, AuthentikProbeDraft)
    if isinstance(draft, JsonResponse):
        return draft
    config = authentik_runtime_config()
    started_at = monotonic()
    outcome = _probe_authentik(
        base_url=draft.authentik_base_url or config.base_url,
        api_token=draft.authentik_api_token or config.api_token,
        timeout_seconds=config.timeout_seconds,
    )
    return _finish(
        actor_id=guard,
        action="authentik_connectivity_tested",
        target_id=PROBE_TARGET_AUTHENTIK,
        outcome=outcome,
        started_at=started_at,
    )


def console_dingtalk_connectivity_test(request: HttpRequest) -> JsonResponse:
    """钉钉统一认证应用: 强制刷新一次新版 accessToken; 不落任何业务数据。"""
    guard = _guard(request, target=PROBE_TARGET_DINGTALK)
    if isinstance(guard, JsonResponse):
        return guard
    draft = _parse_draft(request, DingtalkAppProbeDraft)
    if isinstance(draft, JsonResponse):
        return draft
    config = dingtalk_runtime_config()
    triple = DingTalkCredentialTriple(
        app_key=draft.dingtalk_app_key or config.app_key,
        app_secret=draft.dingtalk_app_secret or config.app_secret,
        agent_id=draft.dingtalk_agent_id or config.agent_id,
    )
    started_at = monotonic()
    outcome = _probe_dingtalk(
        triple,
        timeout_seconds=config.timeout_seconds,
        probe_oapi=False,
    )
    return _finish(
        actor_id=guard,
        action="dingtalk_connectivity_tested",
        target_id=PROBE_TARGET_DINGTALK,
        outcome=outcome,
        started_at=started_at,
    )


def console_dingtalk_notify_connectivity_test(request: HttpRequest) -> JsonResponse:
    """钉钉服务号: 新版 accessToken + 旧版 oapi gettoken 两条授权链路都要过。

    工作通知只有 oapi 版本, 机器人单聊只有新版, 两者共用同一枚服务号凭证却是
    两套独立授权, 任一被拒都会让通知静默失效, 所以必须分别探测。
    """
    guard = _guard(request, target=PROBE_TARGET_DINGTALK_NOTIFY)
    if isinstance(guard, JsonResponse):
        return guard
    draft = _parse_draft(request, DingtalkNotifyProbeDraft)
    if isinstance(draft, JsonResponse):
        return draft
    config = dingtalk_runtime_config()
    started_at = monotonic()
    outcome = _probe_dingtalk(
        _notify_triple(draft),
        timeout_seconds=config.timeout_seconds,
        probe_oapi=True,
    )
    return _finish(
        actor_id=guard,
        action="dingtalk_notify_connectivity_tested",
        target_id=PROBE_TARGET_DINGTALK_NOTIFY,
        outcome=outcome,
        started_at=started_at,
    )


def _notify_triple(draft: DingtalkNotifyProbeDraft) -> DingTalkCredentialTriple:
    """服务号生效凭证: 草稿覆盖落库值, 三项未配齐时按运行时口径回退到统一认证应用。"""
    row = IntegrationSettings.objects.filter(pk=INTEGRATION_SETTINGS_SINGLETON_ID).first()
    app_key = draft.dingtalk_notify_app_key or (row.dingtalk_notify_app_key.strip() if row else "")
    app_secret = draft.dingtalk_notify_app_secret or (
        row.dingtalk_notify_app_secret.strip() if row else ""
    )
    agent_id = draft.dingtalk_notify_agent_id or (
        row.dingtalk_notify_agent_id.strip() if row else ""
    )
    if app_key and app_secret and agent_id:
        return DingTalkCredentialTriple(
            app_key=app_key,
            app_secret=app_secret,
            agent_id=agent_id,
        )
    config = dingtalk_runtime_config()
    return DingTalkCredentialTriple(
        app_key=config.app_key,
        app_secret=config.app_secret,
        agent_id=config.agent_id,
    )


def _probe_authentik(*, base_url: str, api_token: str, timeout_seconds: float) -> ProbeOutcome:
    if not base_url:
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_NOT_CONFIGURED,
            error_message=AUTHENTIK_BASE_URL_MISSING_MESSAGE,
        )
    if not api_token:
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_NOT_CONFIGURED,
            error_message=AUTHENTIK_API_TOKEN_MISSING_MESSAGE,
        )
    try:
        require_secure_url(base_url, allow_local_http=True)
    except InsecureUrlError:
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_INSECURE_BASE_URL,
            error_message=AUTHENTIK_INSECURE_BASE_URL_MESSAGE,
        )
    client = AuthentikAdminClient(
        base_url=base_url,
        api_token=api_token,
        timeout_seconds=timeout_seconds,
    )
    try:
        client.probe_core_users()
    except AuthentikAdminPermissionError as error:
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_UNAUTHORIZED,
            error_message=str(error),
        )
    except AuthentikAdminError as error:
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_UNAVAILABLE,
            error_message=str(error),
        )
    return PROBE_OK


def _probe_dingtalk(
    triple: DingTalkCredentialTriple,
    *,
    timeout_seconds: float,
    probe_oapi: bool,
) -> ProbeOutcome:
    if not triple.is_configured():
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_NOT_CONFIGURED,
            error_message=DINGTALK_CREDENTIALS_MISSING_MESSAGE,
        )
    client = DingTalkApiClient(
        app_key=triple.app_key,
        app_secret=triple.app_secret,
        timeout_seconds=timeout_seconds,
    )
    try:
        _ = client.get_access_token(force_refresh=True)
        if probe_oapi:
            client.probe_oapi_access_token()
    except DingTalkApiError as error:
        return _dingtalk_failure(error)
    return PROBE_OK


def _dingtalk_failure(error: DingTalkApiError) -> ProbeOutcome:
    if isinstance(error, DingTalkApiUnavailableError):
        return ProbeOutcome(
            ok=False,
            error_code=PROBE_ERROR_UNAVAILABLE,
            error_message=str(error),
        )
    unauthorized = isinstance(error, DingTalkApiRequestError) and error.status_code in {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }
    return ProbeOutcome(
        ok=False,
        error_code=PROBE_ERROR_UNAUTHORIZED if unauthorized else PROBE_ERROR_REJECTED,
        error_message=str(error),
    )


def _guard(request: HttpRequest, *, target: str) -> str | JsonResponse:
    """权限 + 方法 + 限流; 通过则返回 actor_id。"""
    actor = require_superuser(request)
    if isinstance(actor, JsonResponse):
        return actor
    if response := require_method(request, "POST"):
        return response
    if rate_limit_exceeded(
        PROBE_RATE_LIMIT_NAMESPACE,
        f"{target}:{actor}",
        limit=PROBE_RATE_LIMIT_MAX,
        window_seconds=PROBE_RATE_LIMIT_WINDOW_SECONDS,
    ):
        return error_response(
            ErrorCode.THROTTLED,
            PROBE_THROTTLED_MESSAGE,
            status=HTTPStatus.TOO_MANY_REQUESTS,
        )
    return actor


def _parse_draft[DraftT: BaseModel](
    request: HttpRequest,
    model: type[DraftT],
) -> DraftT | JsonResponse:
    # 草稿是可选的: 空 body 等价于"全部用落库/环境变量生效值"。
    try:
        return model.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            INVALID_PAYLOAD_MESSAGE,
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


def _finish(
    *,
    actor_id: str,
    action: str,
    target_id: str,
    outcome: ProbeOutcome,
    started_at: float,
) -> JsonResponse:
    latency_ms = max(int((monotonic() - started_at) * 1000), 0)
    _record_probe(
        actor_id=actor_id,
        action=action,
        target_id=target_id,
        outcome=outcome,
        latency_ms=latency_ms,
    )
    return json_response(
        {
            "ok": outcome.ok,
            "latency_ms": latency_ms,
            "error_code": outcome.error_code,
            "error_message": outcome.error_message,
        },
    )


def _record_probe(
    *,
    actor_id: str,
    action: str,
    target_id: str,
    outcome: ProbeOutcome,
    latency_ms: int,
) -> None:
    # 审计元数据不得包含 base_url 之外的配置细节, 更不得包含 token/secret。
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action=action,
            target_type="integration_settings",
            target_id=target_id,
            metadata={
                "ok": outcome.ok,
                "error_code": outcome.error_code,
                "error": outcome.error_message,
                "latency_ms": latency_ms,
            },
        ),
    )
