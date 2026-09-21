import { Ban, BellRing, Gauge, PauseCircle, TrendingDown, type LucideIcon } from "lucide-react";

import type { MessageKey } from "../../../../../i18n/messages";
import type { UsageMetricKey, UsageOverLimitPolicy } from "../usageTypes";
import type { UsageMetricFormState } from "./usageSettingsForm";

export interface PolicyOption {
  value: UsageOverLimitPolicy;
  titleKey: MessageKey;
  descriptionKey: MessageKey;
  icon: LucideIcon;
  /** Webhook 只有一种策略且不可更改: 卡片置灰并解释原因, 而不是把整块藏掉。 */
  locked: boolean;
}

export interface PolicyEffectLine {
  priorityKey: MessageKey | null;
  textKey: MessageKey;
  vars?: Record<string, string | number>;
}

const API_OPTIONS: readonly PolicyOption[] = [
  {
    value: "alert_only",
    titleKey: "usageSettings.policy.api.alert_only.title",
    descriptionKey: "usageSettings.policy.api.alert_only.description",
    icon: BellRing,
    locked: false,
  },
  {
    value: "degrade",
    titleKey: "usageSettings.policy.api.degrade.title",
    descriptionKey: "usageSettings.policy.api.degrade.description",
    icon: TrendingDown,
    locked: false,
  },
  {
    value: "throttle",
    titleKey: "usageSettings.policy.api.throttle.title",
    descriptionKey: "usageSettings.policy.api.throttle.description",
    icon: Gauge,
    locked: false,
  },
  {
    value: "block_all",
    titleKey: "usageSettings.policy.api.block_all.title",
    descriptionKey: "usageSettings.policy.api.block_all.description",
    icon: Ban,
    locked: false,
  },
];

const STREAM_OPTIONS: readonly PolicyOption[] = [
  {
    value: "alert_only",
    titleKey: "usageSettings.policy.stream.alert_only.title",
    descriptionKey: "usageSettings.policy.stream.alert_only.description",
    icon: BellRing,
    locked: false,
  },
  {
    value: "pause_stream",
    titleKey: "usageSettings.policy.stream.pause_stream.title",
    descriptionKey: "usageSettings.policy.stream.pause_stream.description",
    icon: PauseCircle,
    locked: false,
  },
];

const WEBHOOK_OPTIONS: readonly PolicyOption[] = [
  {
    value: "alert_only",
    titleKey: "usageSettings.policy.webhook.alert_only.title",
    descriptionKey: "usageSettings.policy.webhook.alert_only.description",
    icon: BellRing,
    locked: true,
  },
];

export function policyOptions(metric: UsageMetricKey): readonly PolicyOption[] {
  if (metric === "api") {
    return API_OPTIONS;
  }
  return metric === "stream" ? STREAM_OPTIONS : WEBHOOK_OPTIONS;
}

/** 所选策略对 P0/P1/P2 的具体后果; webhook/stream 没有优先级之分, 只给一行说明。 */
export function policyEffectLines(
  metric: UsageMetricKey,
  policy: UsageOverLimitPolicy,
  form: UsageMetricFormState,
): PolicyEffectLine[] {
  if (metric === "webhook") {
    return [{ priorityKey: null, textKey: "usageSettings.effect.webhook.alert_only" }];
  }
  if (metric === "stream") {
    return [
      {
        priorityKey: null,
        textKey:
          policy === "pause_stream"
            ? "usageSettings.effect.stream.pause_stream"
            : "usageSettings.effect.stream.alert_only",
      },
    ];
  }
  return apiEffectLines(policy, form);
}

function apiEffectLines(policy: UsageOverLimitPolicy, form: UsageMetricFormState): PolicyEffectLine[] {
  if (policy === "degrade") {
    return [
      { priorityKey: "usageSettings.priority.p0", textKey: "usageSettings.effect.api.degrade.p0" },
      {
        priorityKey: "usageSettings.priority.p1",
        textKey: "usageSettings.effect.api.degrade.p1",
        vars: { escalation: numberOrDash(form.degradeEscalationPercent) },
      },
      { priorityKey: "usageSettings.priority.p2", textKey: "usageSettings.effect.api.degrade.p2" },
    ];
  }
  if (policy === "throttle") {
    return [
      { priorityKey: "usageSettings.priority.p0", textKey: "usageSettings.effect.api.throttle.p0" },
      {
        priorityKey: "usageSettings.priority.p1",
        textKey: "usageSettings.effect.api.throttle.p1",
        vars: { limit: numberOrDash(form.throttleP1) },
      },
      {
        priorityKey: "usageSettings.priority.p2",
        textKey: "usageSettings.effect.api.throttle.p2",
        vars: { limit: numberOrDash(form.throttleP2) },
      },
    ];
  }
  if (policy === "block_all") {
    return [
      { priorityKey: "usageSettings.priority.p0", textKey: "usageSettings.effect.api.block_all.p0" },
      { priorityKey: "usageSettings.priority.p1", textKey: "usageSettings.effect.api.block_all.other" },
      { priorityKey: "usageSettings.priority.p2", textKey: "usageSettings.effect.api.block_all.other" },
    ];
  }
  return [
    { priorityKey: "usageSettings.priority.p0", textKey: "usageSettings.effect.api.alert_only.all" },
    { priorityKey: "usageSettings.priority.p1", textKey: "usageSettings.effect.api.alert_only.all" },
    { priorityKey: "usageSettings.priority.p2", textKey: "usageSettings.effect.api.alert_only.all" },
  ];
}

function numberOrDash(text: string): string {
  return text.trim() === "" ? "—" : text.trim();
}
