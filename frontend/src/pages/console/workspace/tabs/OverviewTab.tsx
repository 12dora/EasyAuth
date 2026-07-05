import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Fragment, type FormEvent } from "react";
import { useEffect, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../../components/ui/TablePrimitives";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { JsonObject, ListPayload } from "../../../../lib/api";
import type { AppSummary, ConfigurationIssue, ConfigurationStatus } from "../../../../lib/domain";
import { useI18n } from "../../../../i18n/I18nProvider";
import { formatDateTime, readinessLabel, readinessTone } from "../../../../lib/status";
import type { Translator } from "../../../../lib/status";
import { safeJoin } from "../utils";

export function OverviewTab({ appKey, app }: { appKey: string; app?: AppSummary }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [membershipDialogOpen, setMembershipDialogOpen] = useState(false);
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const membershipsQuery = useQuery({
    queryKey: ["console", "app", appKey, "memberships"],
    queryFn: () => apiRequest<ListPayload<MembershipItem>>(`/console/api/v1/apps/${appKey}/memberships`),
    enabled: Boolean(appKey),
  });
  const issues = statusQuery.data?.data ?? [];
  const status = statusQuery.data?.status ?? app?.configuration_status;
  const statusBannerTone = normalizeStatusBannerTone(readinessTone(status));
  const memberships = itemsFromPayload<MembershipItem>(membershipsQuery.data);
  const createMembershipMutation = useMutation({
    mutationFn: (payload: MembershipCreatePayload) =>
      apiRequest(`/console/api/v1/apps/${appKey}/memberships`, {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "memberships"] });
      setMembershipDialogOpen(false);
    },
  });
  const disableMembershipMutation = useMutation({
    mutationFn: (membershipId: number) =>
      apiRequest(`/console/api/v1/apps/${appKey}/memberships/${membershipId}`, {
        method: "PATCH",
        body: { is_active: false },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "memberships"] });
    },
  });
  const canWrite = Boolean(app?.can_manage);
  const membershipColumns = membershipTableColumns({
    t,
    canWrite,
    onDisable: (membershipId) => disableMembershipMutation.mutate(membershipId),
  });
  const membershipTable = useReactTable({
    data: memberships,
    columns: membershipColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const issueColumns: ColumnDef<ConfigurationIssue>[] = [
    { header: t("console.overview.issue.severity"), cell: ({ row }) => row.original.severity ?? row.original.level ?? "-" },
    { header: t("console.overview.issue.subject"), cell: ({ row }) => row.original.subject ?? row.original.target_id ?? "-" },
    { header: t("console.overview.issue.message"), cell: ({ row }) => row.original.message ?? "-" },
    { header: t("console.overview.issue.code"), cell: ({ row }) => <code>{row.original.code ?? "-"}</code> },
  ];
  const issuesTable = useReactTable({
    data: issues,
    columns: issueColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  const issueCount = app?.configuration_summary?.issue_count ?? issues.length;

  return (
    <section className="space-y-6">
      {status && status !== "ready" ? (
        <StatusBanner tone={statusBannerTone} title={t("console.overview.configBanner", { status: readinessLabel(t, status) })} />
      ) : null}
      {statusQuery.error ? (
        <StatusBanner tone="signal" title={t("console.overview.configStatusLoadFailed")} message={(statusQuery.error as Error).message} />
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label={t("console.overview.metric.role")} value={app?.role_count ?? 0} />
        <Metric label={t("console.overview.metric.permission")} value={app?.permission_count ?? 0} />
        <Metric label={t("console.overview.metric.credential")} value={app?.active_credential_count ?? 0} />
        <Metric label={t("console.overview.issues")} value={issueCount} tone={issueCount > 0 ? "signal" : undefined} />
      </div>
      <PanelSurface padding="lg" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">{t("console.overview.basicInfo")}</h2>
          <Badge tone={app?.is_active === false ? "neutral" : "evergreen"}>
            {app?.is_active === false ? t("common.disabled") : t("common.enabled")}
          </Badge>
        </div>
        <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
          <BasicInfoItem label={t("console.overview.field.appName")} value={app?.name || "-"} />
          <BasicInfoItem label={t("console.overview.field.appKey")} value={<code>{app?.app_key || "-"}</code>} />
          <BasicInfoItem label={t("appList.column.owners")} value={safeJoin(app?.owners)} />
          <BasicInfoItem label={t("console.overview.field.developers")} value={safeJoin(app?.developers)} />
          <BasicInfoItem label={t("common.updatedAt")} value={formatDateTime(app?.updated_at)} />
          <BasicInfoItem label={t("console.overview.field.configStatus")} value={`${readinessLabel(t, status)}`} />
        </dl>
        {app?.description ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{app.description}</p> : null}
      </PanelSurface>
      <PanelSurface padding="lg" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">{t("console.overview.members")}</h2>
          {canWrite ? (
            <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setMembershipDialogOpen(true)}>
              {t("common.new")}
            </Button>
          ) : null}
        </div>
        {membershipsQuery.error ? (
          <StatusBanner tone="signal" title={t("console.overview.membersLoadFailed")} message={(membershipsQuery.error as Error).message} />
        ) : null}
        {disableMembershipMutation.error ? (
          <StatusBanner tone="signal" title={t("console.overview.membersOperationFailed")} message={(disableMembershipMutation.error as Error).message} />
        ) : null}
        <TableFrame>
          <TableRoot>
            <TableHead>
              {membershipTable.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHeaderCell key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHeaderCell>
                  ))}
                </TableRow>
              ))}
            </TableHead>
            <TableBody>
              {membershipsQuery.isLoading ? (
                <TableSkeletonRows columns={membershipTable.getAllLeafColumns().length} />
              ) : membershipTable.getRowModel().rows.length > 0 ? (
                membershipTable.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      cell.column.id === "actions" ? (
                        <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                      ) : (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      )
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={membershipTable.getAllLeafColumns().length}>
                  <EmptyState title={t("console.overview.membersEmpty")} description={t("console.overview.membersEmptyDescription")} />
                </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
          <TablePagination table={membershipTable} />
        </TableFrame>
      </PanelSurface>
      {membershipDialogOpen ? (
        <MembershipCreateDialog
          errorMessage={createMembershipMutation.error ? (createMembershipMutation.error as Error).message : ""}
          isSubmitting={createMembershipMutation.isPending}
          onClose={() => setMembershipDialogOpen(false)}
          onSubmit={(payload) => createMembershipMutation.mutate(payload)}
        />
      ) : null}
      <PanelSurface padding="lg" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">{t("console.overview.issues")}</h2>
        </div>
        <TableFrame>
          <TableRoot>
            <TableHead>
              {issuesTable.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHeaderCell key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHeaderCell>
                  ))}
                </TableRow>
              ))}
            </TableHead>
            <TableBody>
              {statusQuery.isLoading ? (
                <TableSkeletonRows columns={issuesTable.getAllLeafColumns().length} />
              ) : issuesTable.getRowModel().rows.length > 0 ? (
                issuesTable.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={issuesTable.getAllLeafColumns().length}>
                  <EmptyState title={t("console.overview.issuesEmpty")} description={t("console.overview.issuesEmptyDescription")} />
                </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
          <TablePagination table={issuesTable} />
        </TableFrame>
      </PanelSurface>
    </section>
  );
}

function BasicInfoItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

export interface AppPatchPayload {
  name: string;
  description: string;
}

interface MembershipCreatePayload {
  user_id: string;
  role: MembershipRole;
}

interface MembershipItem {
  id?: number;
  user_id: string;
  role: MembershipRole | string;
  is_active?: boolean;
}

type MembershipRole = "owner" | "developer";

export function AppBasicInfoDialog({
  app,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  app?: AppSummary;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: AppPatchPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(app?.name ?? "");
  const [description, setDescription] = useState(app?.description ?? "");

  useEffect(() => {
    setName(app?.name ?? "");
    setDescription(app?.description ?? "");
  }, [app?.description, app?.name]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      name: name.trim(),
      description: description.trim(),
    });
  };

  return (
    <Dialog
      title={t("console.overview.editBasicInfoTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="app-basic-info-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="app-basic-info-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("console.overview.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

function MembershipCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: MembershipCreatePayload) => void;
}) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<MembershipRole>("developer");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedUserId = userId.trim();
    if (!normalizedUserId) {
      return;
    }
    onSubmit({ user_id: normalizedUserId, role });
    setUserId("");
  };

  return (
    <Dialog
      title={t("console.overview.createMemberTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="membership-create-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="membership-create-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("console.overview.memberUserId")}>
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} required />
        </Field>
        <Field label={t("console.overview.memberRole")}>
          <SelectInput value={role} onChange={(event) => setRole(event.currentTarget.value as MembershipRole)}>
            <option value="developer">{t("console.overview.roleOption.developer")}</option>
            <option value="owner">{t("console.overview.roleOption.owner")}</option>
          </SelectInput>
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("console.overview.addMemberFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

function membershipTableColumns({
  t,
  canWrite,
  onDisable,
}: {
  t: Translator;
  canWrite: boolean;
  onDisable: (membershipId: number) => void;
}): ColumnDef<MembershipItem>[] {
  return [
    { header: t("common.user"), cell: ({ row }) => <code>{row.original.user_id}</code> },
    { header: t("common.role"), cell: ({ row }) => roleLabel(t, row.original.role) },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>
          {row.original.is_active ? t("common.enabled") : t("common.disabled")}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          {canWrite && row.original.id && row.original.is_active ? (
            <TableRowActionButton type="button" variant="ghost-danger" onClick={() => onDisable(row.original.id as number)}>
              {t("common.disable")}
            </TableRowActionButton>
          ) : null}
        </TableActionCell>
      ),
    },
  ];
}

function roleLabel(t: Translator, role: string): string {
  if (role === "owner") {
    return t("console.overview.role.owner");
  }
  if (role === "developer") {
    return t("console.overview.role.developer");
  }
  return role || "-";
}

function normalizeStatusBannerTone(tone: ReturnType<typeof readinessTone>) {
  return tone === "faint" || tone === "ink" ? "neutral" : tone;
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: "signal" }) {
  return (
    <PanelSurface>
      <span className="text-xs font-semibold text-ink-faint">{label}</span>
      <strong className={`mt-2 block text-2xl font-semibold leading-none ${tone === "signal" ? "text-signal" : "text-ink"}`}>
        {value}
      </strong>
    </PanelSurface>
  );
}
