import type { JsonObject } from "../../lib/api";
import type { Translator } from "../../lib/status";
import type { SettingsCardStatus } from "./SettingsCard";

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
  dingtalk_notify_app_key: string;
  dingtalk_notify_app_secret_configured: boolean;
  dingtalk_notify_agent_id: string;
  dingtalk_notify_work_notice_enabled: boolean;
  dingtalk_notify_robot_enabled: boolean;
  updated_at: string | null;
  updated_by: string;
}

/** 三个「测试连接」端点共用的响应契约。 */
export interface ConnectionTestResult {
  ok: boolean;
  latency_ms: number;
  error_code: string;
  error_message: string;
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

/** 输入框预填的「生效地址」: 有覆盖值用覆盖值, 否则用环境变量回退值。 */
export function effectiveBaseUrl(settings: IntegrationSettingsPayload): string {
  return settings.authentik_base_url_override || settings.authentik_base_url_effective;
}

/** Base URL 输入框下方的来源说明; 未配置时退回通用示例提示。 */
export function baseUrlHint(t: Translator, settings: IntegrationSettingsPayload | undefined): string {
  if (!settings || settings.authentik_base_url_source === "missing") {
    return t("settings.integration.baseUrlHint");
  }
  return t("settings.integration.baseUrlSourceHint", {
    source: sourceLabel(t, settings.authentik_base_url_source),
  });
}

/**
 * PATCH 载荷只包含用户改动过的字段: 未动的字段省略(=保持不变), token 留空同样省略。
 * Base URL 输入框预填的是生效地址, 所以"未改动"要同时对照预填值与落库覆盖值——
 * 否则保存 token 会顺带把环境变量回退悄悄固化成控制台覆盖值。
 */
export function authentikPatchBody(
  settings: IntegrationSettingsPayload | undefined,
  input: { baseUrl: string; apiToken: string },
): JsonObject {
  const body: JsonObject = {};
  if (settings) {
    const next = input.baseUrl.trim();
    if (next !== effectiveBaseUrl(settings) && next !== settings.authentik_base_url_override) {
      body.authentik_base_url = next;
    }
  }
  if (input.apiToken.trim() !== "") {
    body.authentik_api_token = input.apiToken.trim();
  }
  return body;
}

export interface DingtalkAppInput {
  appKey: string;
  appSecret: string;
  agentId: string;
}

export interface DingtalkNotifyInput extends DingtalkAppInput {
  workNoticeEnabled: boolean;
  robotEnabled: boolean;
}

/** 统一认证应用三元组; 只提交改动过的字段, secret 留空表示保持不变。 */
export function dingtalkAppPatchBody(
  settings: IntegrationSettingsPayload | undefined,
  input: DingtalkAppInput,
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

/** 服务号三元组与通知渠道开关; 同样只提交改动过的字段。 */
export function dingtalkNotifyPatchBody(
  settings: IntegrationSettingsPayload | undefined,
  input: DingtalkNotifyInput,
): JsonObject {
  const body: JsonObject = {};
  if (settings && input.appKey.trim() !== settings.dingtalk_notify_app_key) {
    body.dingtalk_notify_app_key = input.appKey.trim();
  }
  if (input.appSecret !== "") {
    body.dingtalk_notify_app_secret = input.appSecret;
  }
  if (settings && input.agentId.trim() !== settings.dingtalk_notify_agent_id) {
    body.dingtalk_notify_agent_id = input.agentId.trim();
  }
  if (settings && input.workNoticeEnabled !== settings.dingtalk_notify_work_notice_enabled) {
    body.dingtalk_notify_work_notice_enabled = input.workNoticeEnabled;
  }
  if (settings && input.robotEnabled !== settings.dingtalk_notify_robot_enabled) {
    body.dingtalk_notify_robot_enabled = input.robotEnabled;
  }
  return body;
}

function status(t: Translator, configured: boolean, missingKey?: "fallback"): SettingsCardStatus {
  if (configured) {
    return { tone: "evergreen", label: t("settings.status.configured") };
  }
  if (missingKey === "fallback") {
    return { tone: "neutral", label: t("settings.dingtalk.notifyStatusFallback") };
  }
  return { tone: "amber", label: t("settings.status.notConfigured") };
}

export function authentikStatus(t: Translator, settings: IntegrationSettingsPayload): SettingsCardStatus {
  return status(t, Boolean(settings.authentik_base_url_effective) && settings.authentik_api_token_configured);
}

export function dingtalkAppStatus(t: Translator, settings: IntegrationSettingsPayload): SettingsCardStatus {
  return status(
    t,
    Boolean(settings.dingtalk_app_key) && settings.dingtalk_app_secret_configured && Boolean(settings.dingtalk_agent_id),
  );
}

/** 服务号三项缺任一就整组回退到统一认证应用, 所以「未配置」要写成回退而不是故障。 */
export function dingtalkNotifyStatus(t: Translator, settings: IntegrationSettingsPayload): SettingsCardStatus {
  return status(
    t,
    Boolean(settings.dingtalk_notify_app_key)
      && settings.dingtalk_notify_app_secret_configured
      && Boolean(settings.dingtalk_notify_agent_id),
    "fallback",
  );
}
