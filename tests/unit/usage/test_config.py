from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from django.core.cache import cache
from pydantic import ValidationError

from easyauth.usage.config import (
    CONFIG_CACHE_KEY,
    DEFAULT_USAGE_CONFIG,
    DEFAULT_USAGE_DOCUMENT,
    UsageConfig,
    UsageConfigVersionConflictError,
    as_document,
    load,
    save,
)
from easyauth.usage.models import UsageSettings

pytestmark = pytest.mark.django_db


def _document() -> dict[str, object]:
    return cast("dict[str, object]", deepcopy(DEFAULT_USAGE_DOCUMENT))


def _section(document: dict[str, object], name: str) -> dict[str, object]:
    section = document[name]
    assert isinstance(section, dict)
    return section


def test_default_document_is_the_agreed_production_schema() -> None:
    config = UsageConfig.model_validate(DEFAULT_USAGE_DOCUMENT)
    dumped = as_document(config)
    assert dumped["api"]["monthly_quota"] == 500000
    assert dumped["api"]["daily_cap"] == 5000
    assert dumped["api"]["over_limit_policy"] == "degrade"
    assert dumped["api"]["degrade_escalation_percent"] == 120
    assert dumped["api"]["throttle_per_hour"] == {"p1": 200, "p2": 20}
    assert dumped["api"]["alert_thresholds_percent"] == [50, 80, 100]
    assert dumped["webhook"]["monthly_quota"] == 50000
    assert dumped["webhook"]["daily_cap"] is None
    assert dumped["webhook"]["over_limit_policy"] == "alert_only"
    assert dumped["stream"]["monthly_quota"] is None
    assert dumped["stream"]["over_limit_policy"] == "alert_only"
    assert dumped["alerts"] == {
        "enabled": True,
        "cooldown_minutes": 60,
        "daily_cap": 30,
        "sender_app_key": "host-ops",
    }
    assert config == DEFAULT_USAGE_CONFIG


def test_extra_field_is_forbidden() -> None:
    document = _document()
    document["unknown"] = 1
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_webhook_rejects_non_alert_only_policy() -> None:
    document = _document()
    _section(document, "webhook")["over_limit_policy"] = "degrade"
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_api_rejects_pause_stream_policy() -> None:
    document = _document()
    _section(document, "api")["over_limit_policy"] = "pause_stream"
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_stream_rejects_block_all_policy() -> None:
    document = _document()
    _section(document, "stream")["over_limit_policy"] = "block_all"
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_thresholds_are_sorted_and_must_be_distinct() -> None:
    document = _document()
    _section(document, "api")["alert_thresholds_percent"] = [100, 50, 80]
    config = UsageConfig.model_validate(document)
    assert config.api.alert_thresholds_percent == (50, 80, 100)
    _section(document, "api")["alert_thresholds_percent"] = [50, 50, 80]
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


@pytest.mark.parametrize("values", [[], [50, 80, 90, 100, 120, 150], [0], [501]])
def test_threshold_bounds(values: list[int]) -> None:
    document = _document()
    _section(document, "api")["alert_thresholds_percent"] = values
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


@pytest.mark.parametrize("quota", [0, 1_000_000_001, True, "500000"])
def test_quota_bounds(quota: object) -> None:
    document = _document()
    _section(document, "api")["monthly_quota"] = quota
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("api", "daily_cap", True),
        ("api", "alert_thresholds_percent", [True, 80, 100]),
        ("alerts", "cooldown_minutes", True),
        ("alerts", "daily_cap", True),
        ("alerts", "cooldown_minutes", "60"),
    ],
)
def test_bool_and_numeric_string_rejected_on_int_fields(
    section: str,
    field: str,
    value: object,
) -> None:
    document = _document()
    _section(document, section)[field] = value
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_bool_rejected_on_throttle() -> None:
    document = _document()
    throttle = _section(document, "api")["throttle_per_hour"]
    assert isinstance(throttle, dict)
    throttle["p1"] = True
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_null_quota_and_cap_are_allowed() -> None:
    document = _document()
    api = _section(document, "api")
    api["monthly_quota"] = None
    api["daily_cap"] = None
    config = UsageConfig.model_validate(document)
    assert config.api.monthly_quota is None
    assert config.api.daily_cap is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("degrade_escalation_percent", 99),
        ("degrade_escalation_percent", 1001),
        ("cooldown_minutes", 4),
        ("cooldown_minutes", 1441),
        ("daily_cap", 0),
        ("daily_cap", 201),
    ],
)
def test_numeric_bounds(field: str, value: int) -> None:
    document = _document()
    if field in {"degrade_escalation_percent"}:
        _section(document, "api")[field] = value
    else:
        _section(document, "alerts")[field] = value
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_throttle_and_anomaly_bounds() -> None:
    document = _document()
    _section(document, "api")["throttle_per_hour"] = {"p1": -1, "p2": 20}
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)
    document = _document()
    anomaly = _section(document, "api")["anomaly"]
    assert isinstance(anomaly, dict)
    anomaly["baseline_multiplier"] = 1.4
    with pytest.raises(ValidationError):
        UsageConfig.model_validate(document)


def test_load_without_row_returns_defaults() -> None:
    assert load() == DEFAULT_USAGE_CONFIG


def test_load_invalid_stored_document_raises() -> None:
    _ = UsageSettings.objects.create(
        pk=1,
        config={"api": "bad"},
        version=1,
        updated_by="tester",
    )
    with pytest.raises(ValidationError):
        load()


def test_save_roundtrip_and_cache_invalidation() -> None:
    document = _document()
    _section(document, "api")["daily_cap"] = 9
    config = UsageConfig.model_validate(document)
    version = save(config, updated_by="alice")
    assert version == 1
    cache.set(CONFIG_CACHE_KEY, as_document(DEFAULT_USAGE_CONFIG), 30)
    save(config, updated_by="alice", expected_version=1)
    loaded = load()
    assert loaded.api.daily_cap == 9
    assert loaded.alerts.sender_app_key == "host-ops"


def test_save_version_conflict() -> None:
    save(DEFAULT_USAGE_CONFIG, updated_by="alice")
    with pytest.raises(UsageConfigVersionConflictError):
        save(DEFAULT_USAGE_CONFIG, updated_by="bob", expected_version=0)
