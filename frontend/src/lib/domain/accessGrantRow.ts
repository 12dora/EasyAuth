/**
 * 控制台授权行契约(与后端 admin_console/grant_row_payloads.serialize_access_grant_row 一一对应)。
 * 供授权明细表、授予权限响应与「当前授权」查询共用; 字段缺失即视为契约违约, 不做静默兜底。
 */

import type { JsonValue } from "../api";
import { bindParse } from "./parse";
import { ACCOUNT_KINDS, type AccountKind } from "./person";

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
  user_account_kind: AccountKind;
  /** 用户头像 URL; 无照片时为空串。 */
  user_avatar_url: string;
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

const GRANT_MEMBERSHIP_SOURCES = ["user", "department"] as const;
const GRANT_SOURCE_TYPES = ["group", "direct"] as const;
const GRANT_LIFECYCLE_TYPES = ["permanent", "timed", "mixed"] as const;

const {
  requireString,
  optionalString,
  requireNullableString,
  requireObjectArray,
  requireEnum,
  requireRecord,
} = bindParse({ fail: (path) => new AccessGrantRowContractError(path) });

export function parseAccessGrantRow(raw: JsonValue): AccessGrantRow {
  const source = requireRecord(raw, "row");
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
    status: requireString(source.status, "status"),
    user_id: requireString(source.user_id, "user_id"),
    user_name: requireString(source.user_name, "user_name"),
    user_department: optionalString(source.user_department, "user_department"),
    user_account_kind: requireEnum(source.user_account_kind, "user_account_kind", ACCOUNT_KINDS),
    user_avatar_url: requireString(source.user_avatar_url, "user_avatar_url"),
    app_key: requireString(source.app_key, "app_key"),
    app_name: requireString(source.app_name, "app_name"),
    app_alias: requireString(source.app_alias, "app_alias"),
    grant_type: requireEnum(source.grant_type, "grant_type", GRANT_LIFECYCLE_TYPES),
    grant_expires_at: requireNullableString(source.grant_expires_at, "grant_expires_at"),
    authorization_groups: requireObjectArray(source.authorization_groups, "authorization_groups").map((item) => ({
      key: requireString(item.key, "key"),
      kind: requireString(item.kind, "kind"),
      name: requireString(item.name, "name"),
      expires_at: requireNullableString(item.expires_at, "expires_at"),
      source: requireEnum(item.source, "source", GRANT_MEMBERSHIP_SOURCES),
    })),
    direct_grants: requireObjectArray(source.direct_grants, "direct_grants").map((item) => ({
      permission: requireString(item.permission, "permission"),
      permission_name: requireString(item.permission_name, "permission_name"),
      scope: requireString(item.scope, "scope"),
      scope_name: requireString(item.scope_name, "scope_name"),
      expires_at: requireNullableString(item.expires_at, "expires_at"),
      source: requireEnum(item.source, "source", GRANT_MEMBERSHIP_SOURCES),
    })),
    groups: requireObjectArray(source.groups, "groups").map((item) => ({
      key: requireString(item.key, "key"),
      kind: requireString(item.kind, "kind"),
      name: requireString(item.name, "name"),
    })),
    grants: requireObjectArray(source.grants, "grants").map((item) => ({
      permission: requireString(item.permission, "permission"),
      scope: requireString(item.scope, "scope"),
      source_type: requireEnum(item.source_type, "source_type", GRANT_SOURCE_TYPES),
      source_key: requireString(item.source_key, "source_key"),
      permission_name: requireString(item.permission_name, "permission_name"),
      permission_name_en: requireString(item.permission_name_en, "permission_name_en"),
      scope_name: requireString(item.scope_name, "scope_name"),
      scope_name_en: requireString(item.scope_name_en, "scope_name_en"),
    })),
  };
}
