import type { Pagination } from "../../lib/api";
import type {
  AuthorizationGroupKind,
  PortalGrant,
  PortalRequest,
  PortalRequestApprover,
} from "../../lib/domain";

interface PortalGrantGroup {
  key: string;
  kind: AuthorizationGroupKind;
  name: string;
}

/**
 * 展开后的单条权限。
 *
 * `permission` / `scope` 是接口 key, `*_name` / `*_name_en` 是目录里的双语显示名:
 * 员工看的是显示名, key 只用来定位。英文名允许为空字符串(目录没配英文名),
 * 中文名在目录行已被删除时回落成 key —— 两者都由后端决定, 前端不再兜底。
 */
interface PortalExpandedGrant {
  permission: string;
  permission_name: string;
  permission_name_en: string;
  scope: string;
  scope_name: string;
  scope_name_en: string;
  source_type: string;
  source_key: string | null;
}

export type PortalGrantRow = PortalGrant & {
  grant_id: number;
  grant_revision: number;
  groups: PortalGrantGroup[];
  grants: PortalExpandedGrant[];
  grant_version: number;
  catalog_version: number;
  snapshot_version: string;
};

interface PortalRequestGroup {
  key: string;
  kind: AuthorizationGroupKind;
  name: string;
}

interface PortalRequestDirectGrant {
  permission: string;
  permission_name: string;
  scope: string;
}

/**
 * 解析后的申请行。
 *
 * 交集里的字段都是 `parsePortalRequestRow` 已经逐个校验过的, 因此在这里收窄成必填:
 * 消费方不必再对着 `PortalRequest` 上的可选签名写「万一没有」的分支。
 */
export type PortalRequestRow = PortalRequest & {
  id: number;
  status: string;
  status_label: string;
  grant_type: string;
  grant_expires_at: string | null;
  reason: string;
  submitted_at: string;
  authorization_groups: PortalRequestGroup[];
  direct_grants: PortalRequestDirectGrant[];
  current_approvers: PortalRequestApprover[];
  decided_by: string;
  decision_actor_type: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_comment: string;
  approved_at: string | null;
  applied_at: string | null;
  withdrawn_at: string | null;
};

export interface PortalListPayload<T> {
  data: T[];
  pagination: Pagination;
}

export function parsePortalGrantList(payload: unknown): PortalListPayload<PortalGrantRow> {
  return parsePortalList(payload, "授权列表", parsePortalGrantRow);
}

export function parsePortalRequestList(payload: unknown): PortalListPayload<PortalRequestRow> {
  return parsePortalList(payload, "申请记录列表", parsePortalRequestRow);
}

function parsePortalList<T>(payload: unknown, label: string, parseRow: (value: unknown, index: number) => T): PortalListPayload<T> {
  const envelope = requireRecord(payload, `${label}响应必须是对象`);
  if (!Array.isArray(envelope.data)) {
    throw new Error(`${label}响应格式无效：data 必须是数组`);
  }
  const pagination = parsePagination(envelope.pagination, label);
  const data = envelope.data.map(parseRow);
  if (data.length > pagination.page_size) {
    throw new Error(`${label}响应格式无效：data 数量超过 page_size`);
  }
  return { data, pagination };
}

function parsePagination(value: unknown, label: string): Pagination {
  const pagination = requireRecord(value, `${label}响应格式无效：pagination 必须是对象`);
  const page = requireInteger(pagination.page, `${label} pagination.page`, 1);
  const pageSize = requireInteger(pagination.page_size, `${label} pagination.page_size`, 1);
  const totalItems = requireInteger(pagination.total_items, `${label} pagination.total_items`, 0);
  const totalPages = requireInteger(pagination.total_pages, `${label} pagination.total_pages`, 0);
  const expectedTotalPages = Math.ceil(totalItems / pageSize);
  if (totalPages !== expectedTotalPages) {
    throw new Error(`${label}响应格式无效：pagination.total_pages 与 total_items/page_size 不一致`);
  }
  return { page, page_size: pageSize, total_items: totalItems, total_pages: totalPages };
}

function parsePortalGrantRow(value: unknown, index: number): PortalGrantRow {
  const label = `授权列表 data[${index}]`;
  const row = requireRecord(value, `${label} 必须是对象`);
  requireString(row.app_key, `${label}.app_key`);
  requireString(row.app_name, `${label}.app_name`);
  // 别名由控制台维护, 应用没配时后端下发空字符串; 字段本身必须存在。
  requireString(row.app_alias, `${label}.app_alias`);
  requireString(row.grant_type, `${label}.grant_type`);
  requireNullableString(row.grant_expires_at, `${label}.grant_expires_at`);
  requireInteger(row.grant_id, `${label}.grant_id`, 1);
  requireInteger(row.grant_revision, `${label}.grant_revision`, 1);
  requireInteger(row.grant_version, `${label}.grant_version`, 0);
  requireInteger(row.catalog_version, `${label}.catalog_version`, 0);
  requireString(row.snapshot_version, `${label}.snapshot_version`);
  requireArray(row.groups, `${label}.groups`).forEach((group, groupIndex) => {
    const itemLabel = `${label}.groups[${groupIndex}]`;
    const item = requireRecord(group, `${itemLabel} 必须是对象`);
    requireString(item.key, `${itemLabel}.key`);
    requireAuthorizationGroupKind(item.kind, `${itemLabel}.kind`);
    requireString(item.name, `${itemLabel}.name`);
  });
  requireArray(row.grants, `${label}.grants`).forEach((grant, grantIndex) => {
    const itemLabel = `${label}.grants[${grantIndex}]`;
    const item = requireRecord(grant, `${itemLabel} 必须是对象`);
    for (const field of ["permission", "permission_name", "permission_name_en", "scope", "scope_name", "scope_name_en", "source_type"] as const) {
      requireString(item[field], `${itemLabel}.${field}`);
    }
    requireNullableString(item.source_key, `${itemLabel}.source_key`);
  });
  return {
    ...row,
    grant_id: row.grant_id,
    grant_revision: row.grant_revision,
    groups: row.groups,
    grants: row.grants,
    grant_version: row.grant_version,
    catalog_version: row.catalog_version,
    snapshot_version: row.snapshot_version,
  } as PortalGrantRow;
}

function parsePortalRequestRow(value: unknown, index: number): PortalRequestRow {
  const label = `申请记录列表 data[${index}]`;
  const row = requireRecord(value, `${label} 必须是对象`);
  requireInteger(row.id, `${label}.id`, 1);
  // app_alias: 应用没配别名时后端下发空字符串; 字段本身必须存在。
  for (const field of ["app_key", "app_name", "app_alias", "request_type", "status", "status_label", "grant_type", "reason", "submitted_at"] as const) {
    requireString(row[field], `${label}.${field}`);
  }
  requireNullableInteger(row.base_grant_id, `${label}.base_grant_id`, 1);
  requireNullableInteger(row.base_grant_revision, `${label}.base_grant_revision`, 1);
  requireNullableString(row.grant_expires_at, `${label}.grant_expires_at`);
  // 申请生命周期上的四个时刻: 审批流程图逐个渲染成节点, 缺一个节点就会静默消失,
  // 因此和 decided_at 一样要求字段必须存在(未到达该阶段时是 null)。
  for (const field of ["decided_at", "approved_at", "applied_at", "withdrawn_at"] as const) {
    requireNullableString(row[field], `${label}.${field}`);
  }
  requireString(row.decision_comment, `${label}.decision_comment`);
  requireString(row.decided_by, `${label}.decided_by`);
  requireString(row.decision_actor_type, `${label}.decision_actor_type`);
  requireNullableString(row.decided_by_name, `${label}.decided_by_name`);
  requireArray(row.authorization_groups, `${label}.authorization_groups`).forEach((group, groupIndex) => {
    const itemLabel = `${label}.authorization_groups[${groupIndex}]`;
    const item = requireRecord(group, `${itemLabel} 必须是对象`);
    requireString(item.key, `${itemLabel}.key`);
    requireAuthorizationGroupKind(item.kind, `${itemLabel}.kind`);
    requireString(item.name, `${itemLabel}.name`);
  });
  requireArray(row.direct_grants, `${label}.direct_grants`).forEach((grant, grantIndex) => {
    const itemLabel = `${label}.direct_grants[${grantIndex}]`;
    const item = requireRecord(grant, `${itemLabel} 必须是对象`);
    requireString(item.permission, `${itemLabel}.permission`);
    requireString(item.permission_name, `${itemLabel}.permission_name`);
    requireString(item.scope, `${itemLabel}.scope`);
  });
  requireArray(row.current_approvers, `${label}.current_approvers`).forEach((approver, approverIndex) => {
    const itemLabel = `${label}.current_approvers[${approverIndex}]`;
    const item = requireRecord(approver, `${itemLabel} 必须是对象`);
    requireString(item.user_id, `${itemLabel}.user_id`);
    requireString(item.name, `${itemLabel}.name`);
  });
  return {
    ...row,
    authorization_groups: row.authorization_groups,
    direct_grants: row.direct_grants,
    current_approvers: row.current_approvers,
    decided_by: row.decided_by,
    decision_actor_type: row.decision_actor_type,
    decided_by_name: row.decided_by_name,
    approved_at: row.approved_at,
    applied_at: row.applied_at,
    withdrawn_at: row.withdrawn_at,
  } as PortalRequestRow;
}

function requireRecord(value: unknown, message: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} 必须是数组`);
  }
  return value;
}

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string") {
    throw new Error(`${label} 必须是字符串`);
  }
}

function requireAuthorizationGroupKind(value: unknown, label: string): asserts value is AuthorizationGroupKind {
  if (value !== "role" && value !== "bundle") {
    throw new Error(`${label} 必须是 role 或 bundle`);
  }
}

function requireNullableString(value: unknown, label: string): asserts value is string | null {
  if (value !== null && typeof value !== "string") {
    throw new Error(`${label} 必须是字符串或 null`);
  }
}

function requireNullableInteger(value: unknown, label: string, minimum: number): number | null {
  if (value === null) {
    return null;
  }
  return requireInteger(value, label, minimum);
}

function requireInteger(value: unknown, label: string, minimum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new Error(`${label} 必须是大于等于 ${minimum} 的整数`);
  }
  return value as number;
}
