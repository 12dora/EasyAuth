/**
 * 控制台授权行契约(与后端 admin_console/grant_row_payloads.serialize_access_grant_row 一一对应)。
 * 供授权明细表、授予权限响应与「当前授权」查询共用; 字段缺失即视为契约违约, 不做静默兜底。
 */

import type { JsonObject, JsonValue } from "../api";

export type GrantMembershipSource = "user" | "department";
export type GrantLifecycleType = "permanent" | "timed" | "mixed";

export interface AccessGrantGroupMembership {
  key: string;
  kind: string;
  name: string;
  expires_at: string | null;
  source: GrantMembershipSource;
}

export interface AccessGrantDirectMembership {
  permission: string;
  permission_name: string;
  scope: string;
  scope_name: string;
  expires_at: string | null;
  source: GrantMembershipSource;
}

export interface EffectiveGrantGroup {
  key: string;
  kind: string;
  name: string;
}

export interface ExpandedGrant {
  permission: string;
  scope: string;
  source_type: "group" | "direct";
  source_key: string;
  permission_name: string;
  permission_name_en: string;
  scope_name: string;
  scope_name_en: string;
}

export interface AccessGrantRow {
  id: number;
  version: number;
  is_current: boolean;
  status: string;
  user_id: string;
  user_name: string;
  /** 用户部门路径; 后端未下发或为空时按空串展示。 */
  user_department?: string;
  app_key: string;
  app_name: string;
  app_alias: string;
  grant_type: GrantLifecycleType;
  grant_expires_at: string | null;
  authorization_groups: AccessGrantGroupMembership[];
  direct_grants: AccessGrantDirectMembership[];
  groups: EffectiveGrantGroup[];
  grants: ExpandedGrant[];
}

export class AccessGrantRowContractError extends Error {
  constructor(field: string) {
    super(`access grant row contract violated: ${field}`);
    this.name = "AccessGrantRowContractError";
  }
}

function requireString(source: JsonObject, field: string): string {
  const value = source[field];
  if (typeof value !== "string") {
    throw new AccessGrantRowContractError(field);
  }
  return value;
}

/** 可选字符串: 缺省或 null 当空串; 给了但不是字符串仍算契约违约。 */
function optionalString(source: JsonObject, field: string): string {
  const value = source[field];
  if (value === undefined || value === null) {
    return "";
  }
  if (typeof value !== "string") {
    throw new AccessGrantRowContractError(field);
  }
  return value;
}

function requireNullableString(source: JsonObject, field: string): string | null {
  const value = source[field];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new AccessGrantRowContractError(field);
  }
  return value;
}

function requireObjectArray(source: JsonObject, field: string): JsonObject[] {
  const value = source[field];
  if (!Array.isArray(value)) {
    throw new AccessGrantRowContractError(field);
  }
  return value.map((item, index) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) {
      throw new AccessGrantRowContractError(`${field}[${index}]`);
    }
    return item as JsonObject;
  });
}

function requireSource(source: JsonObject, field: string): GrantMembershipSource {
  const value = source[field];
  if (value !== "user" && value !== "department") {
    throw new AccessGrantRowContractError(field);
  }
  return value;
}

function requireSourceType(source: JsonObject, field: string): "group" | "direct" {
  const value = source[field];
  if (value !== "group" && value !== "direct") {
    throw new AccessGrantRowContractError(field);
  }
  return value;
}

function requireGrantType(source: JsonObject, field: string): GrantLifecycleType {
  const value = source[field];
  if (value !== "permanent" && value !== "timed" && value !== "mixed") {
    throw new AccessGrantRowContractError(field);
  }
  return value;
}

export function parseAccessGrantRow(raw: JsonValue): AccessGrantRow {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new AccessGrantRowContractError("row");
  }
  const source = raw as JsonObject;
  const id = source.id;
  const version = source.version;
  const isCurrent = source.is_current;
  if (typeof id !== "number" || typeof version !== "number" || typeof isCurrent !== "boolean") {
    throw new AccessGrantRowContractError("id/version/is_current");
  }
  return {
    id,
    version,
    is_current: isCurrent,
    status: requireString(source, "status"),
    user_id: requireString(source, "user_id"),
    user_name: requireString(source, "user_name"),
    user_department: optionalString(source, "user_department"),
    app_key: requireString(source, "app_key"),
    app_name: requireString(source, "app_name"),
    app_alias: requireString(source, "app_alias"),
    grant_type: requireGrantType(source, "grant_type"),
    grant_expires_at: requireNullableString(source, "grant_expires_at"),
    authorization_groups: requireObjectArray(source, "authorization_groups").map((item) => ({
      key: requireString(item, "key"),
      kind: requireString(item, "kind"),
      name: requireString(item, "name"),
      expires_at: requireNullableString(item, "expires_at"),
      source: requireSource(item, "source"),
    })),
    direct_grants: requireObjectArray(source, "direct_grants").map((item) => ({
      permission: requireString(item, "permission"),
      permission_name: requireString(item, "permission_name"),
      scope: requireString(item, "scope"),
      scope_name: requireString(item, "scope_name"),
      expires_at: requireNullableString(item, "expires_at"),
      source: requireSource(item, "source"),
    })),
    groups: requireObjectArray(source, "groups").map((item) => ({
      key: requireString(item, "key"),
      kind: requireString(item, "kind"),
      name: requireString(item, "name"),
    })),
    grants: requireObjectArray(source, "grants").map((item) => ({
      permission: requireString(item, "permission"),
      scope: requireString(item, "scope"),
      source_type: requireSourceType(item, "source_type"),
      source_key: requireString(item, "source_key"),
      permission_name: requireString(item, "permission_name"),
      permission_name_en: requireString(item, "permission_name_en"),
      scope_name: requireString(item, "scope_name"),
      scope_name_en: requireString(item, "scope_name_en"),
    })),
  };
}
