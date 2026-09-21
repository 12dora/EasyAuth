/**
 * 运营分区列表载荷的唯一归一化出口。
 *
 * 分区查询把后端的 `{ data, pagination }` 归一成带判别标签的 `OperationsPayload` 存进
 * react-query 缓存, 因此任何直接写这份缓存的地方必须走同一个函数,
 * 否则缓存里会混进原始信封, 表格读不出行。
 *
 * 授权明细的行按 A1 契约(`parseAccessGrantRow`)解析; 访问申请的审批人按
 * `parseOperationAccessRequestRow` 校验 account_kind; 审计行按
 * `parseAuditLogRow` 校验 actor_person。字段缺失即契约违约,
 * 解析放在取数阶段, 错误直接变成查询/变更错误, 走页面已有的失败态,
 * 不在渲染期炸表格, 也不静默兜底。
 */

import { itemsFromPayload } from "../../../lib/api";
import type { JsonValue, ListPayload, Pagination } from "../../../lib/api";
import { parseAccessGrantRow, type AccessGrantRow } from "../../../lib/domain/accessGrantRow";
import { parseAuditLogRow, parseOperationAccessRequestRow } from "../../../lib/domain/operations";
import type { OperationRow } from "./operationRow";

export type OperationsPayload =
  | { kind: "grants"; pagination?: Pagination; rows: AccessGrantRow[] }
  | { kind: "generic"; pagination?: Pagination; rows: OperationRow[] };

export function operationsPayload(section: string, payload: ListPayload<JsonValue>): OperationsPayload {
  if (section === "access-grants") {
    return {
      kind: "grants",
      pagination: payload.pagination,
      rows: itemsFromPayload<JsonValue>(payload).map(parseAccessGrantRow),
    };
  }
  if (section === "access-requests") {
    return {
      kind: "generic",
      pagination: payload.pagination,
      rows: itemsFromPayload<JsonValue>(payload).map(parseOperationAccessRequestRow),
    };
  }
  if (section === "audit") {
    return {
      kind: "generic",
      pagination: payload.pagination,
      rows: itemsFromPayload<JsonValue>(payload).map(parseAuditLogRow),
    };
  }
  // 未知分区没有解析器可用, 与其静默返回未校验的行, 不如就地失败。
  throw new Error(`Unknown operations section: ${section}`);
}
