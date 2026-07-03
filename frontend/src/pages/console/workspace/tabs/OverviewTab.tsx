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
import type { JsonObject } from "../../../../lib/api";
import type { AppSummary, ConfigurationIssue, ConfigurationStatus } from "../../../../lib/domain";
import { formatDateTime, readinessLabel, readinessTone } from "../../../../lib/status";
import { safeJoin } from "../utils";

export function OverviewTab({ appKey, app }: { appKey: string; app?: AppSummary }) {
  const queryClient = useQueryClient();
  const [membershipDialogOpen, setMembershipDialogOpen] = useState(false);
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const membershipsQuery = useQuery({
    queryKey: ["console", "app", appKey, "memberships"],
    queryFn: () => apiRequest<{ items?: MembershipItem[] }>(`/console/api/v1/apps/${appKey}/memberships`),
    enabled: Boolean(appKey),
  });
  const issues = statusQuery.data?.issues ?? statusQuery.data?.items ?? [];
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
    { header: "级别", cell: ({ row }) => row.original.severity ?? row.original.level ?? "-" },
    { header: "对象", cell: ({ row }) => row.original.subject ?? row.original.target_id ?? "-" },
    { header: "说明", cell: ({ row }) => row.original.message ?? "-" },
    { header: "代码", cell: ({ row }) => <code>{row.original.code ?? "-"}</code> },
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
        <StatusBanner tone={statusBannerTone} title={`配置${readinessLabel(status)}`} />
      ) : null}
      {statusQuery.error ? (
        <StatusBanner tone="signal" title="配置状态加载失败" message={(statusQuery.error as Error).message} />
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="角色" value={app?.role_count ?? 0} />
        <Metric label="权限" value={app?.permission_count ?? 0} />
        <Metric label="活跃凭据" value={app?.active_credential_count ?? 0} />
        <Metric label="配置问题" value={issueCount} tone={issueCount > 0 ? "signal" : undefined} />
      </div>
      <PanelSurface padding="lg" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">基本信息</h2>
          <Badge tone={app?.is_active === false ? "neutral" : "evergreen"}>
            {app?.is_active === false ? "停用" : "启用"}
          </Badge>
        </div>
        <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
          <BasicInfoItem label="应用名称" value={app?.name || "-"} />
          <BasicInfoItem label="应用 Key" value={<code>{app?.app_key || "-"}</code>} />
          <BasicInfoItem label="负责人" value={safeJoin(app?.owners)} />
          <BasicInfoItem label="开发者" value={safeJoin(app?.developers)} />
          <BasicInfoItem label="更新时间" value={formatDateTime(app?.updated_at)} />
          <BasicInfoItem label="配置状态" value={`${readinessLabel(status)}`} />
        </dl>
        {app?.description ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{app.description}</p> : null}
      </PanelSurface>
      <PanelSurface padding="lg" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">成员</h2>
          {canWrite ? (
            <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setMembershipDialogOpen(true)}>
              新建
            </Button>
          ) : null}
        </div>
        {membershipsQuery.error ? (
          <StatusBanner tone="signal" title="成员加载失败" message={(membershipsQuery.error as Error).message} />
        ) : null}
        {disableMembershipMutation.error ? (
          <StatusBanner tone="signal" title="成员操作失败" message={(disableMembershipMutation.error as Error).message} />
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
                  <EmptyState title="暂无成员" description="该应用还没有配置负责人或开发者成员。" />
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
          <h2 className="text-base font-semibold text-ink">配置问题</h2>
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
                  <EmptyState title="暂无配置问题" description="当前应用的授权配置未发现异常。" />
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
      title="编辑基本信息"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            取消
          </Button>
          <Button form="app-basic-info-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            保存
          </Button>
        </>
      }
    >
      <form id="app-basic-info-form" className="grid gap-4" onSubmit={submit}>
        <Field label="名称">
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label="描述">
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title="保存失败" message={errorMessage} /> : null}
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
      title="新建成员"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            取消
          </Button>
          <Button form="membership-create-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            保存
          </Button>
        </>
      }
    >
      <form id="membership-create-form" className="grid gap-4" onSubmit={submit}>
        <Field label="成员用户 ID">
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} required />
        </Field>
        <Field label="成员角色">
          <SelectInput value={role} onChange={(event) => setRole(event.currentTarget.value as MembershipRole)}>
            <option value="developer">开发者（developer）</option>
            <option value="owner">负责人（owner）</option>
          </SelectInput>
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title="新增成员失败" message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

function membershipTableColumns({
  canWrite,
  onDisable,
}: {
  canWrite: boolean;
  onDisable: (membershipId: number) => void;
}): ColumnDef<MembershipItem>[] {
  return [
    { header: "用户", cell: ({ row }) => <code>{row.original.user_id}</code> },
    { header: "角色", cell: ({ row }) => roleLabel(row.original.role) },
    {
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>
          {row.original.is_active ? "启用" : "停用"}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "操作",
      cell: ({ row }) => (
        <TableActionCell>
          {canWrite && row.original.id && row.original.is_active ? (
            <TableRowActionButton type="button" variant="ghost-danger" onClick={() => onDisable(row.original.id as number)}>
              停用
            </TableRowActionButton>
          ) : null}
        </TableActionCell>
      ),
    },
  ];
}

function roleLabel(role: string): string {
  if (role === "owner") {
    return "负责人";
  }
  if (role === "developer") {
    return "开发者";
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
