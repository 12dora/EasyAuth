import type { MessageKey } from "../../../../i18n/messages";
import type { JsonObject } from "../../../../lib/api";
import type { Translator } from "../../../../lib/status";

export const RUN_STATUS_TONES: Record<
  string,
  "evergreen" | "amber" | "signal" | "neutral"
> = {
  success: "evergreen",
  partial: "amber",
  failed: "signal",
};

const RUN_TRIGGER_LABEL_KEYS: Record<string, MessageKey> = {
  periodic: "console.connector.trigger.periodic",
  event: "console.connector.trigger.event",
  manual: "console.connector.trigger.manual",
  offboard: "console.connector.trigger.offboard",
};

const RUN_STATUS_LABEL_KEYS: Record<string, MessageKey> = {
  success: "console.connector.status.success",
  partial: "console.connector.status.partial",
  failed: "console.connector.status.failed",
};

export function runStatusLabel(t: Translator, status: string): string {
  const labelKey = RUN_STATUS_LABEL_KEYS[status];
  return labelKey ? t(labelKey) : status;
}

export function runTriggerLabel(t: Translator, trigger: string): string {
  const labelKey = RUN_TRIGGER_LABEL_KEYS[trigger];
  return labelKey ? t(labelKey) : trigger;
}

export function formatRunStats(stats: Record<string, number>): string {
  const entries = Object.entries(stats);
  if (entries.length === 0) {
    return "-";
  }
  return entries.map(([key, count]) => `${key}=${count}`).join(" ");
}

export function connectorCandidateFingerprint(
  connectorKey: string,
  instanceId: number | null,
  config: JsonObject,
): string {
  return stableJson({ connectorKey, instanceId, config });
}

export function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
