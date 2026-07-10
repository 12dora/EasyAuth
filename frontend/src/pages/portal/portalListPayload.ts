import type { Pagination } from "../../lib/api";
import type { PortalGrant, PortalRequest } from "../../lib/domain";

interface PortalGrantGroup {
  key: string;
  kind: string;
  name: string;
}

interface PortalExpandedGrant {
  permission: string;
  scope: string;
  source_type: string;
  source_key: string | null;
}

export type PortalGrantRow = PortalGrant & {
  groups: PortalGrantGroup[];
  grants: PortalExpandedGrant[];
  grant_version: number;
  catalog_version: number;
  snapshot_version: string;
};

interface PortalRequestGroup {
  key: string;
  kind: string;
  name: string;
}

interface PortalRequestDirectGrant {
  permission: string;
  permission_name: string;
  scope: string;
}

export type PortalRequestRow = PortalRequest & {
  authorization_groups: PortalRequestGroup[];
  direct_grants: PortalRequestDirectGrant[];
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
  requireString(row.grant_type, `${label}.grant_type`);
  requireNullableString(row.grant_expires_at, `${label}.grant_expires_at`);
  requireInteger(row.grant_version, `${label}.grant_version`, 0);
  requireInteger(row.catalog_version, `${label}.catalog_version`, 0);
  requireString(row.snapshot_version, `${label}.snapshot_version`);
  requireArray(row.groups, `${label}.groups`).forEach((group, groupIndex) => {
    const itemLabel = `${label}.groups[${groupIndex}]`;
    const item = requireRecord(group, `${itemLabel} 必须是对象`);
    requireString(item.key, `${itemLabel}.key`);
    requireString(item.kind, `${itemLabel}.kind`);
    requireString(item.name, `${itemLabel}.name`);
  });
  requireArray(row.grants, `${label}.grants`).forEach((grant, grantIndex) => {
    const itemLabel = `${label}.grants[${grantIndex}]`;
    const item = requireRecord(grant, `${itemLabel} 必须是对象`);
    requireString(item.permission, `${itemLabel}.permission`);
    requireString(item.scope, `${itemLabel}.scope`);
    requireString(item.source_type, `${itemLabel}.source_type`);
    requireNullableString(item.source_key, `${itemLabel}.source_key`);
  });
  return row as unknown as PortalGrantRow;
}

function parsePortalRequestRow(value: unknown, index: number): PortalRequestRow {
  const label = `申请记录列表 data[${index}]`;
  const row = requireRecord(value, `${label} 必须是对象`);
  requireInteger(row.id, `${label}.id`, 1);
  for (const field of ["app_key", "app_name", "request_type", "status", "status_label", "grant_type", "reason", "submitted_at"] as const) {
    requireString(row[field], `${label}.${field}`);
  }
  requireNullableString(row.grant_expires_at, `${label}.grant_expires_at`);
  requireNullableString(row.decided_at, `${label}.decided_at`);
  requireString(row.decision_comment, `${label}.decision_comment`);
  requireArray(row.authorization_groups, `${label}.authorization_groups`).forEach((group, groupIndex) => {
    const itemLabel = `${label}.authorization_groups[${groupIndex}]`;
    const item = requireRecord(group, `${itemLabel} 必须是对象`);
    requireString(item.key, `${itemLabel}.key`);
    requireString(item.kind, `${itemLabel}.kind`);
    requireString(item.name, `${itemLabel}.name`);
  });
  requireArray(row.direct_grants, `${label}.direct_grants`).forEach((grant, grantIndex) => {
    const itemLabel = `${label}.direct_grants[${grantIndex}]`;
    const item = requireRecord(grant, `${itemLabel} 必须是对象`);
    requireString(item.permission, `${itemLabel}.permission`);
    requireString(item.permission_name, `${itemLabel}.permission_name`);
    requireString(item.scope, `${itemLabel}.scope`);
  });
  return row as unknown as PortalRequestRow;
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

function requireNullableString(value: unknown, label: string): asserts value is string | null {
  if (value !== null && typeof value !== "string") {
    throw new Error(`${label} 必须是字符串或 null`);
  }
}

function requireInteger(value: unknown, label: string, minimum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new Error(`${label} 必须是大于等于 ${minimum} 的整数`);
  }
  return value as number;
}
