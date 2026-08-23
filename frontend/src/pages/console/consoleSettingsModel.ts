import type { JsonObject } from "../../lib/api";
import type { Translator } from "../../lib/status";

export type IntegrationSourceKind = "override" | "env" | "missing";

export interface IntegrationSettingsPayload {
  authentik_base_url_override: string;
  authentik_base_url_effective: string;
  authentik_base_url_source: IntegrationSourceKind;
  authentik_api_token_configured: boolean;
  authentik_api_token_source: IntegrationSourceKind;
  authentik_source_slug: string;
  dingtalk_app_key: string;
  dingtalk_app_secret_configured: boolean;
  dingtalk_agent_id: string;
  updated_at: string | null;
  updated_by: string;
}

export interface DingtalkTestResult {
  ok: boolean;
  message: string;
}

export const SETTINGS_QUERY_KEY = ["console", "settings", "integrations"];
export const SETTINGS_URL = "/console/api/v1/settings/integrations";

export function sourceLabel(t: Translator, source: IntegrationSourceKind): string {
  if (source === "override") {
    return t("settings.integration.source.override");
  }
  if (source === "env") {
    return t("settings.integration.source.env");
  }
  return t("settings.integration.source.missing");
}

/** PATCH 载荷只包含用户改动过的字段: 未动的字段省略(=保持不变), token 留空同样省略。 */
export function authentikPatchBody(
  settings: IntegrationSettingsPayload | undefined,
  input: { baseUrl: string; apiToken: string },
): JsonObject {
  const body: JsonObject = {};
  if (settings && input.baseUrl.trim() !== settings.authentik_base_url_override) {
    body.authentik_base_url = input.baseUrl.trim();
  }
  if (input.apiToken.trim() !== "") {
    body.authentik_api_token = input.apiToken.trim();
  }
  return body;
}

/** PATCH 载荷只包含用户改动过的字段: 未动的字段省略(=保持不变), secret 留空同样省略。 */
export function dingtalkPatchBody(
  settings: IntegrationSettingsPayload | undefined,
  input: { appKey: string; appSecret: string; agentId: string },
): JsonObject {
  const body: JsonObject = {};
  if (settings && input.appKey.trim() !== settings.dingtalk_app_key) {
    body.dingtalk_app_key = input.appKey.trim();
  }
  if (input.appSecret !== "") {
    body.dingtalk_app_secret = input.appSecret;
  }
  if (settings && input.agentId.trim() !== settings.dingtalk_agent_id) {
    body.dingtalk_agent_id = input.agentId.trim();
  }
  return body;
}
