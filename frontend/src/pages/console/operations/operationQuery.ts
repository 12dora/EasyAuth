import type { MessageKey } from "../../../i18n/messages";

export interface OperationSectionConfig {
  titleKey: MessageKey;
  endpoint: string;
}

export const ENDPOINTS: Record<string, OperationSectionConfig> = {
  "access-requests": { titleKey: "nav.console.accessRequests", endpoint: "/console/api/v1/operations/access-requests" },
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

export const ACCESS_REQUEST_STATUSES = ["submitted", "approved", "rejected", "grant_applied", "grant_failed"] as const;
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
  "access-grants": ["app_key", "user_id", "status", "created_from", "created_to", "version", "current"],
  audit: ["app_key", "actor_id", "created_from", "created_to"],
};

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
    const value = searchParams.get(key);
    if (value) {
      query.set(key, value);
    }
  }
  return query.toString();
}
