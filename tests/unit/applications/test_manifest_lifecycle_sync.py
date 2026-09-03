from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.utils import timezone

from easyauth.admin_console.auto_onboarding_api import (
    AutoOnboardingError,
    repull_app_descriptor,
)
from easyauth.api.errors import ErrorCode
from easyauth.applications.handover_capability import sync_handover_capability_from_manifest
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    App,
)
from easyauth.applications.permission_template_lifecycle import sync_manifest_lifecycle
from easyauth.applications.permission_template_types import (
    AppManifestAppInput,
    AppManifestHandoverAssetTypeInput,
    AppManifestInput,
    AppManifestLifecycleInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
)
from easyauth.lifecycle.handover_actions import initial_action_status_for_app
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
)
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db

HTTPS_PORT: Final = 443
RELATIVE_HANDOVER_PATH: Final = "/api/v1/easyauth/lifecycle/handover"
PUBLIC_BASE_URL: Final = "https://etrade.example.com"
ABSOLUTE_HANDOVER_URL: Final = f"{PUBLIC_BASE_URL}{RELATIVE_HANDOVER_PATH}"
ADMIN_HANDOVER_URL: Final = "https://admin.example.com/handover"
_CUSTOMER_ASSET: Final = AppManifestHandoverAssetTypeInput(
    type="customer",
    label="客户",
    detail_supported=False,
    releasable=False,
)
_CUSTOMER_ASSET_STORED: Final = {
    "type": "customer",
    "label": "客户",
    "detail_supported": False,
    "releasable": False,
}


def test_relative_handover_url_without_base_url_stays_undeclared() -> None:
    app = _app("life-rel-no-base")

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert not AppWebhookConfig.objects.filter(app=app).exists()
    status, blocked_reason, skip_reason, skipped_by = initial_action_status_for_app(app)
    assert status == ACTION_STATUS_BLOCKED
    assert blocked_reason == BLOCKED_REASON_CAPABILITY_UNDECLARED
    assert skip_reason == ""
    assert skipped_by == ""


def test_relative_handover_url_with_public_https_base_url_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app("life-rel-with-base")

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=PUBLIC_BASE_URL,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ABSOLUTE_HANDOVER_URL
    assert config.enabled is True


def test_absolute_public_https_handover_url_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app("life-abs-https")

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=ABSOLUTE_HANDOVER_URL),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    assert AppWebhookConfig.objects.get(app=app).handover_url == ABSOLUTE_HANDOVER_URL


def test_console_overridden_webhook_url_drives_capability_when_usable() -> None:
    app = _app("life-console-usable")
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url=ADMIN_HANDOVER_URL,
        enabled=True,
        updated_by="admin-1",
    )

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ADMIN_HANDOVER_URL
    assert config.updated_by == "admin-1"


def test_console_overridden_empty_webhook_url_keeps_capability_undeclared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app("life-console-empty")
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="",
        enabled=True,
        updated_by="admin-1",
    )

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=ABSOLUTE_HANDOVER_URL),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ""
    assert config.updated_by == "admin-1"


def test_handover_none_on_undeclared_app_does_not_write_none() -> None:
    app = _app("life-none-fresh")

    sync_manifest_lifecycle(
        app=app,
        template=_none_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert app.handover_capability_declared_by == ""


def test_handover_none_does_not_depend_on_persisted_url() -> None:
    declared_at = timezone.now()
    app = App.objects.create(
        app_key="life-none-kept",
        name="life-none-kept",
        handover_capability=HANDOVER_CAPABILITY_NONE,
        handover_capability_declared_by="admin-1",
        handover_capability_declared_at=declared_at,
    )
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url=ADMIN_HANDOVER_URL,
        enabled=True,
        updated_by="admin-1",
    )

    sync_manifest_lifecycle(
        app=app,
        template=_none_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_NONE
    assert app.handover_capability_declared_by == "admin-1"
    assert app.handover_capability_declared_at == declared_at
    assert AppWebhookConfig.objects.get(app=app).handover_url == ADMIN_HANDOVER_URL


def test_processed_undeclared_manifest_clears_stale_asset_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _declared_app_with_assets(monkeypatch, "life-clear-types")

    sync_manifest_lifecycle(
        app=app,
        template=_template(app.app_key, lifecycle=AppManifestLifecycleInput()),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert app.handover_asset_types == []


def test_missing_webhook_url_clears_stale_asset_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _declared_app_with_assets(monkeypatch, "life-clear-url")
    config = AppWebhookConfig.objects.get(app=app)
    config.handover_url = ""
    config.updated_by = "admin-1"
    config.save(update_fields=["handover_url", "updated_by", "updated_at"])

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=ABSOLUTE_HANDOVER_URL),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert app.handover_asset_types == []
    assert AppWebhookConfig.objects.get(app=app).handover_url == ""


def test_unavailable_manifest_keeps_previous_asset_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _declared_app_with_assets(monkeypatch, "life-keep-types")

    sync_handover_capability_from_manifest(app, None, actor_id="system")

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert app.handover_asset_types == [_CUSTOMER_ASSET_STORED]


def test_repull_fetch_failure_keeps_capability_and_asset_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 走真实的重拉入口: descriptor 拉不到时必须原样保留能力与资产类型
    app = _declared_app_with_assets(monkeypatch, "life-repull-fail")
    app.descriptor_base_url = "https://app.example.com"
    app.save(update_fields=["descriptor_base_url", "updated_at"])

    def failing_fetch(_base_url: str, _token: str | None) -> dict[str, object]:
        raise AutoOnboardingError(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "descriptor 拉取失败",
            HTTPStatus.BAD_GATEWAY,
        )

    monkeypatch.setattr(
        "easyauth.admin_console.auto_onboarding_api._fetch_descriptor", failing_fetch
    )

    with pytest.raises(AutoOnboardingError):
        _ = repull_app_descriptor(app=app, actor_id="admin-1")

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    assert app.handover_asset_types == [_CUSTOMER_ASSET_STORED]


def test_repull_malformed_descriptor_keeps_capability_and_asset_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _declared_app_with_assets(monkeypatch, "life-repull-malformed")
    app.descriptor_base_url = "https://app.example.com"
    app.save(update_fields=["descriptor_base_url", "updated_at"])
    monkeypatch.setattr(
        "easyauth.admin_console.auto_onboarding_api._fetch_descriptor",
        lambda _base_url, _token: {"schema_version": "nonsense", "lifecycle": []},
    )

    with pytest.raises(AutoOnboardingError):
        _ = repull_app_descriptor(app=app, actor_id="admin-1")

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    assert app.handover_asset_types == [_CUSTOMER_ASSET_STORED]


def _allow_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "easyauth.config.net_policy.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == HTTPS_PORT else ()),
    )


def _app(app_key: str) -> App:
    return App.objects.create(app_key=app_key, name=app_key)


def _declared_app_with_assets(monkeypatch: pytest.MonkeyPatch, app_key: str) -> App:
    _allow_public_https(monkeypatch)
    app = _app(app_key)
    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(
            app.app_key,
            handover_url=ABSOLUTE_HANDOVER_URL,
            asset_types=(_CUSTOMER_ASSET,),
        ),
        downstream_base_url=None,
        actor_type="system",
    )
    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    assert app.handover_asset_types == [_CUSTOMER_ASSET_STORED]
    return app


def _v2_template(
    app_key: str,
    *,
    handover_url: str,
    asset_types: tuple[AppManifestHandoverAssetTypeInput, ...] = (),
) -> AppManifestInput:
    return _template(
        app_key,
        lifecycle=AppManifestLifecycleInput(
            handover_url=handover_url,
            capabilities=("handover.v2",),
            handover_asset_types=asset_types,
        ),
    )


def _none_template(app_key: str, *, handover_url: str) -> AppManifestInput:
    return _template(
        app_key,
        lifecycle=AppManifestLifecycleInput(
            handover_url=handover_url,
            capabilities=("handover.none",),
        ),
    )


def _template(app_key: str, *, lifecycle: AppManifestLifecycleInput) -> AppManifestInput:
    return AppManifestInput(
        schema_version=1,
        source="paste",
        imported_by="tester",
        raw_template="{}",
        app=AppManifestAppInput(app_key=app_key, name=app_key),
        scopes=(AppManifestScopeInput(key="SELF", name="本人"),),
        permission_groups=(AppManifestPermissionGroupInput(key="core", name="核心"),),
        permissions=(
            AppManifestPermissionInput(
                key="core.read",
                name="查看",
                group_key="core",
                supported_scopes=("SELF",),
            ),
        ),
        authorization_groups=(),
        approval_rules=(),
        lifecycle=lifecycle,
    )
