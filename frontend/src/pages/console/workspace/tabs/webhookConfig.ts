import type { MessageKey } from "../../../../i18n/messages";
import type { WebhookConfigItem, WebhookConfigPayload } from "../../../../lib/domain";

export type WebhookTarget = "approval_callback_url" | "handover_url" | "onboard_url" | "events_url";

export const TARGET_FIELDS: Array<{ target: WebhookTarget; labelKey: MessageKey }> = [
  { target: "approval_callback_url", labelKey: "webhook.field.approvalCallbackUrl" },
  { target: "handover_url", labelKey: "webhook.field.handoverUrl" },
  { target: "onboard_url", labelKey: "webhook.field.onboardUrl" },
  { target: "events_url", labelKey: "webhook.field.eventsUrl" },
];

export type WebhookConfigState =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "unconfigured" }
  | { status: "configured"; config: WebhookConfigItem };

export function parseWebhookConfigPayload(payload: unknown, errorMessage: string): WebhookConfigPayload {
  if (!isRecord(payload) || !("webhook_config" in payload)) {
    throw new Error(errorMessage);
  }
  const config = payload.webhook_config;
  if (config === null) {
    return { webhook_config: null };
  }
  if (
    !isRecord(config) ||
    typeof config.enabled !== "boolean" ||
    typeof config.secret_configured !== "boolean" ||
    typeof config.approval_callback_url !== "string" ||
    typeof config.handover_url !== "string" ||
    typeof config.onboard_url !== "string" ||
    typeof config.events_url !== "string" ||
    (config.secret !== undefined && typeof config.secret !== "string") ||
    (config.updated_by !== undefined && typeof config.updated_by !== "string") ||
    (config.updated_at !== undefined && config.updated_at !== null && typeof config.updated_at !== "string")
  ) {
    throw new Error(errorMessage);
  }
  return { webhook_config: config as unknown as WebhookConfigPayload["webhook_config"] };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
