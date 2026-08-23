import { useQuery } from "@tanstack/react-query";
import { getCoreRowModel, getPaginationRowModel, useReactTable } from "@tanstack/react-table";
import type { ColumnDef, PaginationState } from "@tanstack/react-table";
import { useState } from "react";

import { useI18n } from "../../../i18n/I18nProvider";
import type { Translator } from "../../../lib/status";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import { operationColumns } from "./operationColumns";
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
  const table = useOperationsTable({
    rows,
    isPaginated,
    pagination: params.pagination,
    pageCount: query.data?.pagination?.total_pages ?? 1,
    onPaginationChange: params.updatePagination,
    columns: sectionColumns(section, t, accessRequestMutations, {
      emergencyRevokeMutation,
      openEmergencyRevoke,
    }),
  });

  return {
    section,
    isPaginated,
    searchParams: params.searchParams,
    updateSearchParam: params.updateSearchParam,
    query,
    rows,
    table,
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

/** 只有对应分区才注入行内动作列, 其余分区保持只读表格。 */
function sectionColumns(
  section: string,
  t: Translator,
  accessRequest: AccessRequestMutations,
  emergency: EmergencyRevokeControls,
): ColumnDef<OperationRow>[] {
  return operationColumns(
    section,
    t,
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

interface OperationsTableInput {
  rows: OperationRow[];
  columns: ColumnDef<OperationRow>[];
  isPaginated: boolean;
  pagination: PaginationState;
  pageCount: number;
  onPaginationChange: (
    updater: PaginationState | ((current: PaginationState) => PaginationState),
  ) => void;
}

function useOperationsTable(input: OperationsTableInput) {
  return useReactTable({
    data: input.rows,
    columns: input.columns,
    getCoreRowModel: getCoreRowModel(),
    ...(input.isPaginated
      ? {
          manualPagination: true as const,
          pageCount: input.pageCount,
          state: { pagination: input.pagination },
          onPaginationChange: input.onPaginationChange,
        }
      : {
          getPaginationRowModel: getPaginationRowModel(),
        }),
  });
}
