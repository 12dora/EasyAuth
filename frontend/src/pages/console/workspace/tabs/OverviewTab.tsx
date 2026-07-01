import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { DataTable } from "../../../../components/DataTable";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type { AppSummary, ConfigurationStatus } from "../../../../lib/domain";
import { readinessLabel, readinessTone } from "../../../../lib/status";

export function OverviewTab({ appKey, app }: { appKey: string; app?: AppSummary }) {
  const queryClient = useQueryClient();
  const [basicInfoEditing, setBasicInfoEditing] = useState(false);
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
  const memberships = itemsFromPayload<MembershipItem>(membershipsQuery.data);
  const isAdmin = isConsoleAdmin();
  const canEditBasicInfo = Boolean(app?.can_manage);
  const patchAppMutation = useMutation({
    mutationFn: (payload: AppPatchPayload) =>
      apiRequest(`/console/api/v1/apps/${appKey}`, {
        method: "PATCH",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey] });
      setBasicInfoEditing(false);
    },
  });
  const createMembershipMutation = useMutation({
    mutationFn: (payload: MembershipCreatePayload) =>
      apiRequest(`/console/api/v1/apps/${appKey}/memberships`, {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "memberships"] });
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
  const membershipColumns = membershipTableColumns({
    canWrite: isAdmin,
    onDisable: (membershipId) => disableMembershipMutation.mutate(membershipId),
  });

  return (
    <section className="workspace-grid">
      <div className="metric-grid">
        <Metric label="角色" value={app?.role_count ?? 0} />
        <Metric label="权限" value={app?.permission_count ?? 0} />
        <Metric label="活跃凭据" value={app?.active_credential_count ?? 0} />
        <Metric label="配置问题" value={app?.configuration_summary?.issue_count ?? issues.length} />
      </div>
      <StatusBanner tone={readinessTone(status)} title={`配置${readinessLabel(status)}`} />
      <section className="stack">
        <div className="panel-toolbar">
          <h2>基本信息</h2>
          {canEditBasicInfo ? (
            <Button
              onClick={() => {
                patchAppMutation.reset();
                setBasicInfoEditing(true);
              }}
              type="button"
            >
              编辑基本信息
            </Button>
          ) : null}
        </div>
        {canEditBasicInfo && basicInfoEditing ? (
          <AppBasicInfoForm
            app={app}
            errorMessage={patchAppMutation.error ? (patchAppMutation.error as Error).message : ""}
            isSubmitting={patchAppMutation.isPending}
            onSubmit={(payload) => patchAppMutation.mutate(payload)}
          />
        ) : null}
      </section>
      <section className="stack">
        <div className="panel-toolbar">
          <h2>成员</h2>
        </div>
        {isAdmin ? (
          <MembershipCreateForm
            errorMessage={createMembershipMutation.error ? (createMembershipMutation.error as Error).message : ""}
            isSubmitting={createMembershipMutation.isPending}
            onSubmit={(payload) => createMembershipMutation.mutate(payload)}
          />
        ) : null}
        {membershipsQuery.error ? (
          <StatusBanner tone="danger" title="成员加载失败" message={(membershipsQuery.error as Error).message} />
        ) : null}
        {disableMembershipMutation.error ? (
          <StatusBanner tone="danger" title="成员操作失败" message={(disableMembershipMutation.error as Error).message} />
        ) : null}
        <DataTable
          data={memberships}
          columns={membershipColumns}
          emptyText={membershipsQuery.isLoading ? "加载中" : "暂无成员"}
        />
      </section>
      <DataTable
        data={issues}
        columns={[
          { header: "级别", cell: ({ row }) => row.original.severity ?? row.original.level ?? "-" },
          { header: "对象", cell: ({ row }) => row.original.subject ?? row.original.target_id ?? "-" },
          { header: "说明", cell: ({ row }) => row.original.message ?? "-" },
          { header: "代码", cell: ({ row }) => <code>{row.original.code ?? "-"}</code> },
        ]}
        emptyText={statusQuery.isLoading ? "加载中" : "暂无配置问题"}
      />
    </section>
  );
}

interface AppPatchPayload {
  name: string;
  description: string;
  is_active: boolean;
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

function AppBasicInfoForm({
  app,
  errorMessage,
  isSubmitting,
  onSubmit,
}: {
  app?: AppSummary;
  errorMessage: string;
  isSubmitting: boolean;
  onSubmit: (payload: AppPatchPayload) => void;
}) {
  const [name, setName] = useState(app?.name ?? "");
  const [description, setDescription] = useState(app?.description ?? "");
  const [isActive, setIsActive] = useState(app?.is_active ?? true);

  useEffect(() => {
    setName(app?.name ?? "");
    setDescription(app?.description ?? "");
    setIsActive(app?.is_active ?? true);
  }, [app?.description, app?.is_active, app?.name]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      name: name.trim(),
      description: description.trim(),
      is_active: isActive,
    });
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <Field label="名称">
        <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
      </Field>
      <Field label="描述">
        <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
      </Field>
      <label className="field">
        <span className="field-label">状态</span>
        <span>
          <input
            aria-label="启用应用"
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.currentTarget.checked)}
          />{" "}
          启用应用
        </span>
      </label>
      <Button type="submit" variant="primary" disabled={isSubmitting}>
        保存
      </Button>
      {errorMessage ? <StatusBanner tone="danger" title="保存失败" message={errorMessage} /> : null}
    </form>
  );
}

function MembershipCreateForm({
  errorMessage,
  isSubmitting,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
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
    <form className="form-grid" onSubmit={submit}>
      <Field label="成员用户 ID">
        <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} required />
      </Field>
      <Field label="成员角色">
        <SelectInput value={role} onChange={(event) => setRole(event.currentTarget.value as MembershipRole)}>
          <option value="developer">developer</option>
          <option value="owner">owner</option>
        </SelectInput>
      </Field>
      <Button type="submit" variant="primary" disabled={isSubmitting}>
        新增成员
      </Button>
      {errorMessage ? <StatusBanner tone="danger" title="新增成员失败" message={errorMessage} /> : null}
    </form>
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
        <Badge tone={row.original.is_active ? "success" : "neutral"}>
          {row.original.is_active ? "启用" : "停用"}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) =>
        canWrite && row.original.id && row.original.is_active ? (
          <Button variant="danger" onClick={() => onDisable(row.original.id as number)}>
            停用
          </Button>
        ) : null,
    },
  ];
}

function roleLabel(role: string): string {
  if (role === "owner") {
    return "owner";
  }
  if (role === "developer") {
    return "developer";
  }
  return role || "-";
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function isConsoleAdmin(): boolean {
  const role =
    document.body.dataset.currentUserRole ??
    document.documentElement.dataset.currentUserRole ??
    document.getElementById("easyauth-root")?.dataset.currentUserRole ??
    "";
  return role === "EasyAuth Admins";
}
