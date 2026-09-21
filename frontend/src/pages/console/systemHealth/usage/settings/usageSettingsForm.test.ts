import { describe, expect, test } from "vitest";

import type { UsageAnomalyConfig, UsageConfig } from "../usageTypes";
import { documentToForm, formToDocument, validateForm } from "./usageSettingsForm";

const ANOMALY: UsageAnomalyConfig = {
  enabled: true,
  hourly_absolute: null,
  baseline_multiplier: 5,
  baseline_min_calls: 200,
};

/** 契约 §2 的默认文档, 作为往返映射的基准样本。 */
const DEFAULT_DOCUMENT: UsageConfig = {
  api: {
    monthly_quota: 500000,
    daily_cap: 5000,
    alert_thresholds_percent: [50, 80, 100],
    over_limit_policy: "degrade",
    degrade_escalation_percent: 120,
    throttle_per_hour: { p1: 200, p2: 20 },
    anomaly: ANOMALY,
  },
  webhook: {
    monthly_quota: 50000,
    daily_cap: null,
    alert_thresholds_percent: [50, 80, 100],
    over_limit_policy: "alert_only",
    anomaly: ANOMALY,
  },
  stream: {
    monthly_quota: null,
    daily_cap: null,
    alert_thresholds_percent: [50, 80, 100],
    over_limit_policy: "alert_only",
    anomaly: ANOMALY,
  },
  alerts: { enabled: true, cooldown_minutes: 60, daily_cap: 30, sender_app_key: "host-ops" },
};

describe("用量设置表单模型", () => {
  test("默认文档经表单往返后与原文档一致", () => {
    expect(formToDocument(documentToForm(DEFAULT_DOCUMENT))).toEqual(DEFAULT_DOCUMENT);
  });

  test("webhook/stream 不写出 api 专属的降级与限流字段", () => {
    const written = formToDocument(documentToForm(DEFAULT_DOCUMENT));

    expect(Object.keys(written.webhook).sort()).toEqual([
      "alert_thresholds_percent",
      "anomaly",
      "daily_cap",
      "monthly_quota",
      "over_limit_policy",
    ]);
    expect(Object.keys(written.stream)).not.toContain("throttle_per_hour");
  });

  test("空配额写回 null, 阈值按升序写回", () => {
    const form = documentToForm(DEFAULT_DOCUMENT);
    form.api.monthlyQuota = "";
    form.api.dailyCap = "  ";
    form.api.thresholds = [100, 30, 80];

    const written = formToDocument(form);

    expect(written.api.monthly_quota).toBeNull();
    expect(written.api.daily_cap).toBeNull();
    expect(written.api.alert_thresholds_percent).toEqual([30, 80, 100]);
  });

  test("默认文档校验通过", () => {
    expect(validateForm(documentToForm(DEFAULT_DOCUMENT))).toEqual({});
  });

  test("配额越界、非整数与必填项都落到对应字段路径上", () => {
    const form = documentToForm(DEFAULT_DOCUMENT);
    form.api.monthlyQuota = "0";
    form.webhook.dailyCap = "12.5";
    form.alerts.cooldownMinutes = "";
    form.alerts.senderAppKey = "   ";
    form.stream.anomaly.baselineMultiplier = "1";

    const errors = validateForm(form);

    expect(errors["api.monthly_quota"]?.key).toBe("usageSettings.error.integerRange");
    expect(errors["api.monthly_quota"]?.vars).toEqual({ min: 1, max: 1_000_000_000 });
    expect(errors["webhook.daily_cap"]?.key).toBe("usageSettings.error.integerRange");
    expect(errors["alerts.cooldown_minutes"]?.key).toBe("usageSettings.error.required");
    expect(errors["alerts.sender_app_key"]?.key).toBe("usageSettings.error.required");
    expect(errors["stream.anomaly.baseline_multiplier"]?.key).toBe("usageSettings.error.numberRange");
  });

  test("阈值数量与重复值各自给出提示", () => {
    const tooMany = documentToForm(DEFAULT_DOCUMENT);
    tooMany.api.thresholds = [10, 20, 30, 40, 50, 60];
    const duplicated = documentToForm(DEFAULT_DOCUMENT);
    duplicated.api.thresholds = [50, 50];
    const empty = documentToForm(DEFAULT_DOCUMENT);
    empty.api.thresholds = [];

    expect(validateForm(tooMany)["api.alert_thresholds_percent"]?.key).toBe("usageSettings.error.thresholdCount");
    expect(validateForm(empty)["api.alert_thresholds_percent"]?.key).toBe("usageSettings.error.thresholdCount");
    expect(validateForm(duplicated)["api.alert_thresholds_percent"]?.key).toBe("usageSettings.error.thresholdRange");
  });

  test("限流上限允许 0, 超过区间则报错", () => {
    const zero = documentToForm(DEFAULT_DOCUMENT);
    zero.api.throttleP2 = "0";
    const tooLarge = documentToForm(DEFAULT_DOCUMENT);
    tooLarge.api.throttleP1 = "100001";

    expect(validateForm(zero)["api.throttle_per_hour.p2"]).toBeUndefined();
    expect(validateForm(tooLarge)["api.throttle_per_hour.p1"]?.key).toBe("usageSettings.error.integerRange");
    expect(formToDocument(zero).api.throttle_per_hour.p2).toBe(0);
  });
});
