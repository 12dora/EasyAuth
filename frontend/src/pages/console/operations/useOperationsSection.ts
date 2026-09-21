import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  ORDERING_PARAM,
  sortStateFromOrdering,
  sortValueFromSorter,
  type AppTableProps,
  type ColumnsType,
  type FilterValue,
  type SorterResult,
  type TableCurrentDataSource,
  type TablePaginationConfig,
} from "../../../components/antd/AppTable";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { JsonValue, ListPayload } from "../../../lib/api";
import type { AccessGrantRow } from "../../../lib/domain/accessGrantRow";
import { accessGrantColumns, operationColumns, type OperationFilterValues } from "./operationColumns";
import { SECTION_FILTER_MAPS, filterValuesFromSearchParams } from "./operationFilterMap";
import { useAccessRequestMutations, useRevokeGrantMutation } from "./operationMutations";
import { operationsPayload, type OperationsPayload } from "./operationPayload";
import { operationQueryString, SECTION_ORDERING_FIELDS, type OperationSectionConfig } from "./operationQuery";
import type { AccessRequestAction, OperationNotice, OperationRow } from "./operationRow";
import { useOperationsSearchParams } from "./operationsSearchParams";

export type OperationsSectionController = ReturnType<typeof useOperationsSection>;

/** 带行内动作列的分区必须给 AppTable 传 minWidth, 否则 antd 无法固定右列。 */
const SECTION_MIN_WIDTH: Record<string, number | undefined> = {
  "access-requests": 1400,
  "access-grants": 1260,
};

/** antd 回调的第四个参数只用到 action; 收窄成这一项后同一个处理函数能给任意行类型用。 */
type TableChangeExtra = { action: TableCurrentDataSource<never>["action"] };

interface OperationsTableModel<T> {
  rows: T[];
  columns: ColumnsType<T>;
  rowKey: (row: T) => string;
  minWidth?: number;
  tableProps: Pick<AppTableProps<T>, "pagination" | "onChange">;
}

export type OperationsTableState =
  | ({ kind: "grants" } & OperationsTableModel<AccessGrantRow>)
  | ({ kind: "generic" } & OperationsTableModel<OperationRow>);

export function useOperationsSection(section: string, config: OperationSectionConfig) {
  const { t } = useI18n();
  const isAccessGrants = section === "access-grants";
  const params = useOperationsSearchParams();
  const [pendingAction, setPendingAction] = useState<AccessRequestAction | null>(null);
  const [pendingRevokeGrant, setPendingRevokeGrant] = useState<AccessGrantRow | null>(null);
  const [operationNotice, setOperationNotice] = useState<OperationNotice | null>(null);
  const queryString = operationQueryString(section, params.searchParams, params.pagination);

  const query = useQuery({
    queryKey: ["console", "operations", section, queryString],
    queryFn: async (): Promise<OperationsPayload> => {
      const payload = await apiRequest<ListPayload<JsonValue>>(`${config.endpoint}?${queryString}`);
      return operationsPayload(section, payload);
    },
  });
  const controls = { setPendingAction, setPendingRevokeGrant, setOperationNotice };
  const accessRequestMutations = useAccessRequestMutations(controls);
  const { revokeGrantMutation, openRevokeGrant } = useRevokeGrantMutation(controls);

  const grantRows = query.data?.kind === "grants" ? query.data.rows : [];
  const genericRows = query.data?.kind === "generic" ? query.data.rows : [];
  const rowCount = grantRows.length + genericRows.length;
  const filterMap = SECTION_FILTER_MAPS[section];
  const filterValues: OperationFilterValues = useMemo(
    () => (filterMap ? filterValuesFromSearchParams(params.searchParams, filterMap) : {}),
    [filterMap, params.searchParams],
  );
  const totalItems = query.data?.pagination?.total_items ?? rowCount;
  const orderingMap = SECTION_ORDERING_FIELDS[section];
  const sort = useMemo(
    () => sortStateFromOrdering(params.searchParams.get(ORDERING_PARAM), orderingMap ?? {}),
    [orderingMap, params.searchParams],
  );

  // 服务端分区: 分页、筛选、排序都由 URL 承载(FF-21 深链), antd 只负责回传变更。
  // 排序的序列化与 useServerTable 同一份(orderingSerializer / sortValueFromSorter)。
  const onChange = (
    nextPagination: TablePaginationConfig,
    nextFilters: Record<string, FilterValue | null>,
    nextSorter: unknown,
    extra: TableChangeExtra,
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
      return;
    }
    if (extra.action === "sort" && orderingMap) {
      params.updateSort(
        sortValueFromSorter(nextSorter as SorterResult<OperationRow> | SorterResult<OperationRow>[]),
        orderingMap,
      );
    }
  };

  const tableProps = {
    pagination: {
      current: params.pagination.page,
      pageSize: params.pagination.pageSize,
      total: totalItems,
    },
    onChange,
  };

  const requestActionsDisabled =
    accessRequestMutations.decisionMutation.isPending ||
    accessRequestMutations.reassignMutation.isPending ||
    accessRequestMutations.retryGrantMutation.isPending;
  // 列定义每次渲染重建会让 antd 整表重挂(表头筛选下拉随之关闭), 因此按真正的输入缓存。
  const grantColumns = useMemo(
    () =>
      accessGrantColumns(t, filterValues, sort, {
        disabled: revokeGrantMutation.isPending,
        onRevoke: openRevokeGrant,
      }),
    // openRevokeGrant 每次渲染都是新闭包, 但它只调用 mutation.reset 与 setState, 行为恒定,
    // 因此不进依赖数组 —— 否则这个 useMemo 每次渲染都会失效。
    [t, filterValues, sort, revokeGrantMutation.isPending],
  );
  const genericColumns = useMemo(
    () =>
      operationColumns(
        section,
        t,
        filterValues,
        sort,
        section === "access-requests"
          ? { disabled: requestActionsDisabled, onAction: accessRequestMutations.openAccessRequestAction }
          : undefined,
      ),
    // openAccessRequestAction 同上: 每次渲染新建但行为恒定, 不进依赖数组。
    [section, t, filterValues, sort, requestActionsDisabled],
  );

  const table: OperationsTableState = isAccessGrants
    ? {
        kind: "grants",
        rows: grantRows,
        columns: grantColumns,
        rowKey: (row) => String(row.id),
        minWidth: SECTION_MIN_WIDTH[section],
        tableProps,
      }
    : {
        kind: "generic",
        rows: genericRows,
        columns: genericColumns,
        rowKey: sectionRowKey(section),
        minWidth: SECTION_MIN_WIDTH[section],
        tableProps,
      };

  return {
    section,
    searchParams: params.searchParams,
    updateSearchParam: params.updateSearchParam,
    updateSearchParams: params.updateSearchParams,
    query,
    rowCount,
    table,
    operationNotice,
    pendingAction,
    closePendingAction: () => setPendingAction(null),
    pendingRevokeGrant,
    closeRevokeGrant: () => setPendingRevokeGrant(null),
    accessRequestMutations,
    revokeGrantMutation,
  };
}

/** 行身份只能取自数据字段; 审计行没有 id, 用后端返回的事件要素组合。 */
function sectionRowKey(section: string): (row: OperationRow) => string {
  if (section === "audit") {
    return (row) => [row.created_at, row.event_type, row.actor_id, row.target_type, row.target_id].join("|");
  }
  return (row) => String(row.id);
}

function normalizeFilters(filters: Record<string, FilterValue | null>): Record<string, string[]> {
  const normalized: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value && value.length > 0) {
      normalized[key] = value.map(String);
    }
  }
  return normalized;
}
