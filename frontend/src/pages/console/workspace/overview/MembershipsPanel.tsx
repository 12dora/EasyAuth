import { getCoreRowModel, getPaginationRowModel, useReactTable } from "@tanstack/react-table";
import { Plus } from "lucide-react";

import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { TableView } from "../../../../components/ui/TableView";
import { membershipTableColumns } from "./overviewColumns";
import type { MembershipItem } from "./overviewModel";

export function MembershipsPanel({
  canWrite,
  memberships,
  isLoading,
  loadError,
  operationError,
  onCreate,
  onDisable,
}: {
  canWrite: boolean;
  memberships: MembershipItem[];
  isLoading: boolean;
  loadError: Error | null;
  operationError: Error | null;
  onCreate: () => void;
  onDisable: (membershipId: number) => void;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: memberships,
    columns: membershipTableColumns({ t, canWrite, onDisable }),
    getRowId: (membership) => String(membership.id),
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.overview.members")}</h2>
        {canWrite ? (
          <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={onCreate}>
            {t("common.new")}
          </Button>
        ) : null}
      </div>
      {loadError ? (
        <StatusBanner live="alert" tone="signal" title={t("console.overview.membersLoadFailed")} message={loadError.message} />
      ) : null}
      {operationError ? (
        <StatusBanner live="alert" tone="signal" title={t("console.overview.membersOperationFailed")} message={operationError.message} />
      ) : null}
      <TableView
        table={table}
        totalItems={memberships.length}
        isLoading={isLoading}
        empty={<EmptyState title={t("console.overview.membersEmpty")} description={t("console.overview.membersEmptyDescription")} />}
      />
    </PanelSurface>
  );
}
