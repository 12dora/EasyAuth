import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { AppTableProps, ColumnsType, TableProps } from "../../../components/antd/AppTable";
import { useI18n } from "../../../i18n/I18nProvider";
import type { Translator } from "../../../lib/status";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import { operationColumns, type OperationFilterValues } from "./operationColumns";
import { SECTION_FILTER_MAPS, filterValuesFromSearchParams } from "./operationFilterMap";
import {
  useAccessRequestMutations,
  useEmergencyRevokeMutation,
  useHealthCheckMutation,
  type AccessRequestMutations,
  type EmergencyRevokeControls,
} from "./operationMutations";
import { operationQueryString, type OperationSectionConfig } from "./operationQuery";
import type { AccessRequestAction, OperationNotice, OperationRow } from "./operationRow";
import { useOperationsSearchParams } from "./operationsSearchParams";

export type OperationsSectionController = ReturnType<typeof useOperationsSection>;

/** 带行内动作列的分区必须给 AppTable 传 minWidth, 否则 antd 无法固定右列。 */
const SECTION_MIN_WIDTH: Record<string, number | undefined> = {
  "access-requests": 1240,
  "access-grants": 1360,
};

export function useOperationsSection(section: string, config: OperationSectionConfig) {
  const { t } = useI18n();
  // 依赖健康返回非分页的 list_payload; 其余分区走后端分页, 需按分区区分表格模式。
  const isPaginated = section !== "dependency-health";
  const params = useOperationsSearchParams();
  const [pendingAction, setPendingAction] = useState<AccessRequestAction | null>(null);
  const [pendingEmergencyRevoke, setPendingEmergencyRevoke] = useState<OperationRow | null>(null);
  const [operationNotice, setOperationNotice] = useState<OperationNotice | null>(null);
  const queryString = isPaginated
    ? operationQueryString(section, params.searchParams, params.pagination)
    : "";

  const query = useQuery({
    queryKey: isPaginated
      ? ["console", "operations", section, queryString]
      : ["console", "operations", section],
    queryFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        isPaginated ? `${config.endpoint}?${queryString}` : config.endpoint,
      ),
  });
  const healthCheckMutation = useHealthCheckMutation();
  const controls = { setPendingAction, setPendingEmergencyRevoke, setOperationNotice };
  const accessRequestMutations = useAccessRequestMutations(controls);
  const { emergencyRevokeMutation, openEmergencyRevoke } = useEmergencyRevokeMutation(controls);

  const rows = itemsFromPayload<OperationRow>(query.data);
  const filterMap = SECTION_FILTER_MAPS[section];
  const filterValues: OperationFilterValues = filterMap
    ? filterValuesFromSearchParams(params.searchParams, filterMap)
    : {};
  const totalItems = query.data?.pagination?.total_items ?? rows.length;

  // 服务端分区: 分页与筛选状态都由 URL 承载(FF-21 深链), antd 只负责回传变更。
  const onChange: NonNullable<TableProps<OperationRow>["onChange"]> = (
    nextPagination,
    nextFilters,
    _sorter,
    extra,
  ) => {
    if (extra.action === "paginate") {
      params.updatePagination({
        page: nextPagination.current ?? params.pagination.page,
        pageSize: nextPagination.pageSize ?? params.pagination.pageSize,
      });
      return;
    }
    if (extra.action === "filter" && filterMap) {
      params.updateFilters(normalizeFilters(nextFilters), filterMap);
    }
  };

  const tableProps: Pick<AppTableProps<OperationRow>, "pagination" | "onChange"> = isPaginated
    ? {
        pagination: {
          current: params.pagination.page,
          pageSize: params.pagination.pageSize,
          total: totalItems,
        },
        onChange,
      }
    : {};

  return {
    section,
    searchParams: params.searchParams,
    updateSearchParam: params.updateSearchParam,
    query,
    rows,
    columns: sectionColumns(section, t, filterValues, accessRequestMutations, {
      emergencyRevokeMutation,
      openEmergencyRevoke,
    }),
    rowKey: sectionRowKey(section),
    minWidth: SECTION_MIN_WIDTH[section],
    tableProps,
    healthCheckMutation,
    operationNotice,
    pendingAction,
    closePendingAction: () => setPendingAction(null),
    pendingEmergencyRevoke,
    closeEmergencyRevoke: () => setPendingEmergencyRevoke(null),
    accessRequestMutations,
    emergencyRevokeMutation,
  };
}

/** 行身份只能取自数据字段; 审计行没有 id, 用后端返回的事件要素组合。 */
function sectionRowKey(section: string): (row: OperationRow) => string {
  if (section === "dependency-health") {
    return (row) => String(row.component);
  }
  if (section === "audit") {
    return (row) => [row.created_at, row.event_type, row.actor_id, row.target_type, row.target_id].join("|");
  }
  return (row) => String(row.id);
}

/** 只有对应分区才注入行内动作列, 其余分区保持只读表格。 */
function sectionColumns(
  section: string,
  t: Translator,
  filters: OperationFilterValues,
  accessRequest: AccessRequestMutations,
  emergency: EmergencyRevokeControls,
): ColumnsType<OperationRow> {
  return operationColumns(
    section,
    t,
    filters,
    section === "access-requests"
      ? {
          disabled:
            accessRequest.decisionMutation.isPending ||
            accessRequest.reassignMutation.isPending ||
            accessRequest.retryGrantMutation.isPending,
          onAction: accessRequest.openAccessRequestAction,
        }
      : undefined,
    section === "access-grants"
      ? {
          disabled: emergency.emergencyRevokeMutation.isPending,
          onEmergencyRevoke: emergency.openEmergencyRevoke,
        }
      : undefined,
  );
}

type TableFilterState = Parameters<NonNullable<TableProps<OperationRow>["onChange"]>>[1];

function normalizeFilters(filters: TableFilterState): Record<string, string[]> {
  const normalized: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value && value.length > 0) {
      normalized[key] = value.map(String);
    }
  }
  return normalized;
}
