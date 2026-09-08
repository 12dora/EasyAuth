import type { MessageKey } from "../../../i18n/messages";

export interface OperationSectionConfig {
  titleKey: MessageKey;
  endpoint: string;
  /** 分区自己的副标题; 省略时用运营页通用副标题。 */
  descriptionKey?: MessageKey;
}

export const ENDPOINTS: Record<string, OperationSectionConfig> = {
  "access-requests": {
    titleKey: "nav.console.accessRequests",
    endpoint: "/console/api/v1/operations/access-requests",
    descriptionKey: "console.operations.accessRequests.description",
  },
  "access-grants": { titleKey: "nav.console.accessGrants", endpoint: "/console/api/v1/operations/access-grants" },
  "dependency-health": { titleKey: "nav.console.dependencyHealth", endpoint: "/console/api/v1/operations/dependency-health" },
  "blocked-apps": {
    titleKey: "nav.console.blockedApps",
    endpoint: "/console/api/v1/lifecycle/handover-blocked-apps",
  },
  audit: { titleKey: "console.operations.title.audit", endpoint: "/console/api/v1/audit-logs" },
};

/** 与后端 operation_filters.DEFAULT_PAGE_SIZE 保持一致。 */
export const DEFAULT_PAGE_SIZE = 20;

/** 1 基页码, 与 antd 分页一致。 */
export interface OperationsPagination {
  page: number;
  pageSize: number;
}

/** 与后端 access_requests.models.REQUEST_STATUS_VALUES 对齐; 顺序即状态筛选下拉的顺序。 */
export const ACCESS_REQUEST_STATUSES = [
  "submitted",
  "approved",
  "rejected",
  "grant_applied",
  "grant_failed",
  "grant_conflict",
  "grant_expired",
  "withdrawn",
] as const;

/**
 * 「待审批」页的默认状态口径。
 *
 * 页面标题就是「待审批」, 所以未选状态时只取 submitted, 而不是把已批准/已驳回/已授权
 * 全都列出来。要看历史必须在状态筛选里显式选另一个状态, 或者选「全部」——
 * 「全部」是一个显式取值(URL 上 `status=all`, 请求时不带 status 参数), 因此
 * 清空/重置筛选(URL 上没有 status)回到的是待审批, 而不是全部历史。
 */
export const ACCESS_REQUEST_DEFAULT_STATUS = "submitted";
export const ALL_STATUSES_VALUE = "all";

/** 待审批页要发给后端的 status; 返回 null 表示「全部」, 不带该参数。 */
export function accessRequestStatusParam(searchParams: URLSearchParams): string | null {
  const status = searchParams.get("status") || ACCESS_REQUEST_DEFAULT_STATUS;
  return status === ALL_STATUSES_VALUE ? null : status;
}
export const ACCESS_GRANT_STATUSES = ["active", "revoked", "expired"] as const;

export function paginationFromSearchParams(searchParams: URLSearchParams): OperationsPagination {
  return {
    page: positiveInteger(searchParams.get("page"), 1),
    pageSize: positiveInteger(searchParams.get("page_size"), DEFAULT_PAGE_SIZE),
  };
}

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

const SECTION_FILTER_KEYS: Record<string, string[]> = {
  "access-requests": ["app_key", "user_id", "status", "created_from", "created_to"],
  "access-grants": ["app_key", "user_id", "status", "created_from", "created_to"],
  audit: ["app_key", "actor_id", "created_from", "created_to"],
};

/**
 * 授权明细默认只列当前版本(`current_only=true`), 历史版本由表格上方的开关打开。
 * 开关状态挂在 URL 上, 与其余筛选条件一样可深链。
 */
export const INCLUDE_HISTORY_PARAM = "include_history";

export function includeHistoryFromSearchParams(searchParams: URLSearchParams): boolean {
  return searchParams.get(INCLUDE_HISTORY_PARAM) === "1";
}

export function operationQueryString(
  section: string,
  searchParams: URLSearchParams,
  pagination: OperationsPagination,
): string {
  const query = new URLSearchParams({
    page: String(pagination.page),
    page_size: String(pagination.pageSize),
  });
  const filterKeys = SECTION_FILTER_KEYS[section] ?? [];
  for (const key of filterKeys) {
    const value =
      section === "access-requests" && key === "status"
        ? accessRequestStatusParam(searchParams)
        : searchParams.get(key);
    if (value) {
      query.set(key, value);
    }
  }
  if (section === "access-grants") {
    query.set("current_only", includeHistoryFromSearchParams(searchParams) ? "false" : "true");
  }
  return query.toString();
}
