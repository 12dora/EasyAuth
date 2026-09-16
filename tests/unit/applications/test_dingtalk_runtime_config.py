from __future__ import annotations

import pytest
from django.test import override_settings

from easyauth.applications.integration_settings import (
    IntegrationSettings,
    dingtalk_runtime_config,
)

pytestmark = pytest.mark.django_db


@override_settings(
    EASYAUTH_DINGTALK_APP_KEY="env-key",
    EASYAUTH_DINGTALK_APP_SECRET="env-secret",
    EASYAUTH_DINGTALK_AGENT_ID="env-agent",
)
def test_notify_triple_falls_back_to_main_when_any_notify_field_blank() -> None:
    row = IntegrationSettings.load()
    row.dingtalk_app_key = "main-key"
    row.dingtalk_app_secret = "main-secret"
    row.dingtalk_agent_id = "1001"
    row.dingtalk_notify_app_key = "svc-key"
    row.dingtalk_notify_app_secret = "svc-secret"
    row.dingtalk_notify_agent_id = ""
    row.save()

    config = dingtalk_runtime_config()

    assert config.app_key == "main-key"
    assert config.app_secret == "main-secret"
    assert config.agent_id == "1001"
    assert config.notify.app_key == "main-key"
    assert config.notify.app_secret == "main-secret"
    assert config.notify.agent_id == "1001"


@override_settings(
    EASYAUTH_DINGTALK_APP_KEY="env-key",
    EASYAUTH_DINGTALK_APP_SECRET="env-secret",
    EASYAUTH_DINGTALK_AGENT_ID="env-agent",
)
def test_notify_triple_uses_settings_row_when_all_three_set() -> None:
    row = IntegrationSettings.load()
    row.dingtalk_app_key = "main-key"
    row.dingtalk_app_secret = "main-secret"
    row.dingtalk_agent_id = "1001"
    row.dingtalk_notify_app_key = "svc-key"
    row.dingtalk_notify_app_secret = "svc-secret"
    row.dingtalk_notify_agent_id = "9001"
    row.save()

    config = dingtalk_runtime_config()

    assert config.app_key == "main-key"
    assert config.notify.app_key == "svc-key"
    assert config.notify.app_secret == "svc-secret"
    assert config.notify.agent_id == "9001"


@override_settings(
    EASYAUTH_DINGTALK_APP_KEY="env-key",
    EASYAUTH_DINGTALK_APP_SECRET="env-secret",
    EASYAUTH_DINGTALK_AGENT_ID="env-agent",
)
def test_notify_triple_falls_back_to_env_main_when_settings_empty() -> None:
    config = dingtalk_runtime_config()

    assert config.app_key == "env-key"
    assert config.notify.app_key == "env-key"
    assert config.notify.app_secret == "env-secret"
    assert config.notify.agent_id == "env-agent"
