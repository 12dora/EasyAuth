import type { ConfigurationIssue, ConfigurationStatus, SecretPayload } from "../../../lib/domain";
import type { CreatedCredentialKind, CredentialKindPath, ManifestDiffItem, ManifestPreviewPayload } from "./types";

export function detectTemplateFormat(content: string): "json" | "yaml" {
  return content.trimStart().startsWith("{") ? "json" : "yaml";
}

export function manifestContentFingerprint(content: string): string {
  const normalized = content.replace(/\r\n?/g, "\n").trim();
  let hash = 2166136261;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${normalized.length}:${(hash >>> 0).toString(16)}`;
}

export function parseConfigurationStatus(payload: unknown, expectedAppKey: string): ConfigurationStatus {
  if (
    !isRecord(payload) ||
    payload.app_key !== expectedAppKey ||
    !["blocking", "warning", "ready"].includes(String(payload.status)) ||
    !Array.isArray(payload.data) ||
    !payload.data.every(isConfigurationIssue) ||
    (payload.status === "ready" ? payload.data.length !== 0 : payload.data.length === 0)
  ) {
    throw new Error("配置状态响应格式无效。");
  }
  return payload as unknown as ConfigurationStatus;
}

function isConfigurationIssue(value: unknown): value is ConfigurationIssue {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.code === "string" &&
    ["blocking", "warning", "info"].includes(String(value.severity)) &&
    value.level === value.severity &&
    typeof value.message === "string" &&
    typeof value.subject === "string" &&
    typeof value.target_type === "string" &&
    typeof value.target_id === "string"
  );
}

export function isBlockingIssue(issue: ConfigurationIssue): boolean {
  return (issue.severity ?? issue.level) === "blocking";
}

export function parseOAuthAccessToken(payload: unknown): string {
  if (!isRecord(payload) || typeof payload.access_token !== "string" || !payload.access_token) {
    throw new Error("OAuth token 响应格式无效。");
  }
  return payload.access_token;
}

export function parseManifestImportResult(
  payload: unknown,
): { catalog_version?: string | number; template_version?: string | number } {
  if (!isRecord(payload)) {
    throw new Error("Manifest 导入响应格式无效。");
  }
  const version = payload.catalog_version ?? payload.template_version;
  if (
    (typeof version !== "string" && typeof version !== "number") ||
    String(version).length === 0
  ) {
    throw new Error("Manifest 导入响应格式无效。");
  }
  return typeof payload.catalog_version === "string" || typeof payload.catalog_version === "number"
    ? { catalog_version: payload.catalog_version }
    : { template_version: payload.template_version as string | number };
}

export function parseCredentialSecretPayload(
  payload: unknown,
  requestedKind: CredentialKindPath,
): SecretPayload & { credential: NonNullable<SecretPayload["credential"]>; one_time_secret: Record<string, string> } {
  const expectedKind = requestedKind === "static-tokens" ? "static_token" : "oauth_client";
  if (
    !isRecord(payload) ||
    !isRecord(payload.credential) ||
    payload.credential.kind !== expectedKind ||
    !isRecord(payload.one_time_secret) ||
    payload.one_time_secret.kind !== expectedKind
  ) {
    throw new Error("凭据创建响应格式无效。");
  }
  if (!hasRequiredSecretMaterial(payload.one_time_secret, expectedKind)) {
    throw new Error("凭据创建响应格式无效。");
  }
  return payload as unknown as SecretPayload & {
    credential: NonNullable<SecretPayload["credential"]>;
    one_time_secret: Record<string, string>;
  };
}

function hasRequiredSecretMaterial(oneTimeSecret: Record<string, unknown>, expectedKind: CreatedCredentialKind): boolean {
  if (expectedKind === "static_token") {
    return typeof oneTimeSecret.app_token === "string" && oneTimeSecret.app_token.length > 0;
  }
  return (
    typeof oneTimeSecret.client_id === "string" &&
    oneTimeSecret.client_id.length > 0 &&
    typeof oneTimeSecret.client_secret === "string" &&
    oneTimeSecret.client_secret.length > 0
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function diffFromChanges(
  changes: Array<{ action?: string; key?: string; parent_key?: string }>,
): NonNullable<ManifestPreviewPayload["diff"]> {
  return {
    added: changes.filter((change) => change.action?.startsWith("create")).map(changeItem),
    changed: changes.filter((change) => change.action?.startsWith("update")).map(changeItem),
    removed: changes.filter((change) => change.action?.startsWith("deactivate")).map(changeItem),
  };
}

function changeItem(change: { action?: string; key?: string; parent_key?: string }): ManifestDiffItem {
  return {
    type: change.action,
    key: change.key,
    name: change.parent_key,
  };
}
