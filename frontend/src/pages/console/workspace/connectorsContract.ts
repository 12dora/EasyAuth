import type { ListPayload } from "../../../lib/api";
import type { AuthorizationGroupItem, ConnectorMappingItem } from "../../../lib/domain";

export interface ConnectorMappingsPayload extends ListPayload<ConnectorMappingItem> {
  data: ConnectorMappingItem[];
  revision: string;
}

export function parseConnectorIntervalSeconds(value: string): number {
  if (!/^\d+$/.test(value)) {
    throw new Error("连接器对账间隔必须为整数秒。");
  }
  const seconds = Number(value);
  if (!Number.isSafeInteger(seconds) || seconds < 60 || seconds > 86400) {
    throw new Error("连接器对账间隔必须在 60 到 86400 秒之间。");
  }
  return seconds;
}

export function parseAuthorizationGroupsPayload(
  payload: unknown,
): ListPayload<AuthorizationGroupItem> {
  const envelope = requireRecord(payload, "授权组响应格式无效。");
  const data = requireArray(envelope.data, "授权组响应 data 必须是数组。").map(
    parseAuthorizationGroup,
  );
  return {
    ...envelope,
    data,
  } as ListPayload<AuthorizationGroupItem>;
}

export function parseConnectorMappingsPayload(payload: unknown): ConnectorMappingsPayload {
  const envelope = requireRecord(payload, "连接器映射响应格式无效。");
  if (typeof envelope.revision !== "string" || envelope.revision.length === 0) {
    throw new Error("连接器映射响应格式无效。");
  }
  const data = requireArray(envelope.data, "连接器映射响应 data 必须是数组。").map(
    parseConnectorMapping,
  );
  return {
    ...envelope,
    revision: envelope.revision,
    data,
  } as ConnectorMappingsPayload;
}

function parseAuthorizationGroup(value: unknown): AuthorizationGroupItem {
  const row = requireRecord(value, "授权组响应格式无效。");
  if (
    typeof row.kind !== "string" ||
    typeof row.key !== "string" ||
    row.key.length === 0 ||
    typeof row.name !== "string" ||
    typeof row.requestable !== "boolean" ||
    typeof row.is_active !== "boolean" ||
    !Array.isArray(row.grants)
  ) {
    throw new Error("授权组响应格式无效。");
  }
  return {
    id: optionalNumber(row.id),
    app_key: optionalString(row.app_key),
    key: row.key,
    kind: row.kind,
    name: row.name,
    name_en: optionalString(row.name_en),
    description: optionalString(row.description),
    description_en: optionalString(row.description_en),
    requestable: row.requestable,
    is_active: row.is_active,
    grants: row.grants.map((grant) => {
      const item = requireRecord(grant, "授权组响应格式无效。");
      if (
        typeof item.permission !== "string" ||
        typeof item.scope !== "string" ||
        typeof item.is_active !== "boolean"
      ) {
        throw new Error("授权组响应格式无效。");
      }
      return {
        permission: item.permission,
        scope: item.scope,
        is_active: item.is_active,
      };
    }),
  };
}

function parseConnectorMapping(value: unknown): ConnectorMappingItem {
  const row = requireRecord(value, "连接器映射响应格式无效。");
  if (
    typeof row.authorization_group_key !== "string" ||
    row.authorization_group_key.length === 0 ||
    typeof row.authorization_group_name !== "string" ||
    typeof row.external_ref !== "string" ||
    typeof row.auto_create !== "boolean"
  ) {
    throw new Error("连接器映射响应格式无效。");
  }
  return {
    authorization_group_key: row.authorization_group_key,
    authorization_group_name: row.authorization_group_name,
    external_ref: row.external_ref,
    auto_create: row.auto_create,
  };
}

function requireRecord(value: unknown, message: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, message: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(message);
  }
  return value;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
