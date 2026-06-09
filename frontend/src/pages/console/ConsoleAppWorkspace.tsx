import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, KeyRound, Play, Plus, RefreshCcw, RotateCw, ShieldOff } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { CodeBlock } from "../../components/CodeBlock";
import { DataTable } from "../../components/DataTable";
import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { SecretDialog } from "../../components/SecretDialog";
import { StatusBanner } from "../../components/StatusBanner";
import { Toast } from "../../components/Toast";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import { credentialDisablePathSegment } from "../../lib/credentials";
import type {
  AppListPayload,
  AppSummary,
  ApprovalRuleItem,
  ConfigurationStatus,
  CredentialItem,
  IntegrationGuide,
  MatrixPayload,
  PermissionGroupItem,
  PermissionItem,
  PermissionTreePayload,
  QueryTestResult,
  RoleItem,
  SecretPayload,
} from "../../lib/domain";
import { queryClient } from "../../lib/query";
import { formatDateTime, readinessLabel, readinessTone } from "../../lib/status";

type WorkspaceTab = "overview" | "catalog" | "matrix" | "rules" | "credentials" | "test" | "guide";

const TABS: Array<{ key: WorkspaceTab; label: string }> = [
  { key: "overview", label: "总览" },
  { key: "catalog", label: "权限目录" },
  { key: "matrix", label: "矩阵" },
  { key: "rules", label: "审批规则" },
  { key: "credentials", label: "凭据" },
  { key: "test", label: "联调" },
  { key: "guide", label: "接入说明" },
];

export function ConsoleAppWorkspace() {
  const { appKey = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = (searchParams.get("tab") as WorkspaceTab | null) ?? "overview";
  const activeTab = TABS.some((item) => item.key === tab) ? tab : "overview";

  const appQuery = useQuery({
    queryKey: ["console", "app", appKey],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps/${appKey}`),
    enabled: Boolean(appKey),
  });
  const app = appQuery.data?.app;

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title={app?.name ?? appKey}
        description={app?.description || "应用授权配置、接入凭据和联调入口。"}
        actions={<Link className="button button-secondary" to="/console">返回应用列表</Link>}
      />
      {appQuery.error ? (
        <StatusBanner tone="danger" title="应用加载失败" message={(appQuery.error as Error).message} />
      ) : null}
      <div className="tabbar">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={item.key === activeTab ? "active" : ""}
            onClick={() => setSearchParams({ tab: item.key })}
          >
            {item.label}
          </button>
        ))}
      </div>
      {activeTab === "overview" ? <OverviewTab appKey={appKey} app={app} /> : null}
      {activeTab === "catalog" ? <CatalogTab appKey={appKey} /> : null}
      {activeTab === "matrix" ? <MatrixTab appKey={appKey} /> : null}
      {activeTab === "rules" ? <RulesTab appKey={appKey} /> : null}
      {activeTab === "credentials" ? <CredentialsTab appKey={appKey} /> : null}
      {activeTab === "test" ? <QueryTestTab appKey={appKey} /> : null}
      {activeTab === "guide" ? <GuideTab appKey={appKey} /> : null}
    </>
  );
}

function OverviewTab({ appKey, app }: { appKey: string; app?: AppSummary }) {
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const issues = statusQuery.data?.issues ?? statusQuery.data?.items ?? [];
  const status = statusQuery.data?.status ?? app?.configuration_status;

  return (
    <section className="workspace-grid">
      <div className="metric-grid">
        <Metric label="角色" value={app?.role_count ?? 0} />
        <Metric label="权限" value={app?.permission_count ?? 0} />
        <Metric label="活跃凭据" value={app?.active_credential_count ?? 0} />
        <Metric label="配置问题" value={app?.configuration_summary?.issue_count ?? issues.length} />
      </div>
      <StatusBanner tone={readinessTone(status)} title={`配置${readinessLabel(status)}`} />
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

function CatalogTab({ appKey }: { appKey: string }) {
  const treeQuery = useQuery({
    queryKey: ["console", "app", appKey, "permission-tree"],
    queryFn: () => apiRequest<PermissionTreePayload>(`/console/api/v1/apps/${appKey}/permission-tree`),
  });
  const rolesQuery = useQuery({
    queryKey: ["console", "app", appKey, "roles"],
    queryFn: () => apiRequest<{ items?: RoleItem[] }>(`/console/api/v1/apps/${appKey}/roles`),
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<{ items?: PermissionItem[] }>(`/console/api/v1/apps/${appKey}/permissions`),
  });
  const groups = flattenGroups(treeQuery.data?.groups ?? []);
  const roles = itemsFromPayload<RoleItem>(rolesQuery.data);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);

  return (
    <div className="two-column">
      <DataTable
        data={groups}
        columns={[
          { header: "模块", cell: ({ row }) => <code>{row.original.key}</code> },
          { header: "名称", accessorKey: "name" },
          { header: "权限数", cell: ({ row }) => row.original.permissions?.length ?? 0 },
        ]}
        emptyText={treeQuery.isLoading ? "加载中" : "暂无权限分组"}
      />
      <div className="stack">
        <DataTable
          data={roles}
          columns={[
            { header: "Role", cell: ({ row }) => <code>{row.original.key}</code> },
            { header: "名称", accessorKey: "name" },
            { header: "可申请", cell: ({ row }) => <Badge tone={row.original.requestable ? "success" : "neutral"}>{row.original.requestable ? "是" : "否"}</Badge> },
          ]}
          emptyText="暂无角色"
        />
        <DataTable
          data={permissions}
          columns={[
            { header: "Permission", cell: ({ row }) => <code>{row.original.key}</code> },
            { header: "名称", accessorKey: "name" },
            { header: "分组", cell: ({ row }) => row.original.group_key || "-" },
          ]}
          emptyText="暂无权限"
        />
      </div>
    </div>
  );
}

function MatrixTab({ appKey }: { appKey: string }) {
  const matrixQuery = useQuery({
    queryKey: ["console", "app", appKey, "matrix"],
    queryFn: () => apiRequest<MatrixPayload>(`/console/api/v1/apps/${appKey}/role-permission-matrix`),
  });
  const [changed, setChanged] = useState<Map<string, boolean>>(new Map());
  const matrix = matrixQuery.data;
  const cells = new Map((matrix?.cells ?? []).map((cell) => [`${cell.role_id}:${cell.permission_id}`, cell.enabled]));
  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<MatrixPayload>(`/console/api/v1/apps/${appKey}/role-permission-matrix`, {
        method: "PATCH",
        body: {
          base_version: matrix?.version ?? "",
          assignments: Array.from(changed.entries()).map(([key, enabled]) => {
            const [roleId, permissionId] = key.split(":").map(Number);
            return { role_id: roleId, permission_id: permissionId, enabled };
          }),
          add: [],
          remove: [],
        },
      }),
    onSuccess: () => {
      setChanged(new Map());
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "matrix"] });
    },
  });

  return (
    <section className="matrix-panel">
      <div className="panel-toolbar">
        <span>目录版本 <code>{matrix?.version?.slice(0, 12) ?? "-"}</code></span>
        <Button
          variant="primary"
          icon={<Check size={16} />}
          disabled={changed.size === 0 || saveMutation.isPending || !matrix?.version}
          onClick={() => saveMutation.mutate()}
        >
          保存变更
        </Button>
      </div>
      {saveMutation.error ? <StatusBanner tone="danger" title="保存失败" message={(saveMutation.error as Error).message} /> : null}
      <div className="matrix-scroll">
        <table className="matrix-table">
          <thead>
            <tr>
              <th>Permission</th>
              {(matrix?.roles ?? []).map((role) => (
                <th key={role.id}>{role.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(matrix?.permissions ?? []).map((permission) => (
              <tr key={permission.id}>
                <td>
                  <strong>{permission.name}</strong>
                  <code>{permission.key}</code>
                </td>
                {(matrix?.roles ?? []).map((role) => {
                  const key = `${role.id}:${permission.id}`;
                  const checked = changed.get(key) ?? cells.get(key) ?? false;
                  return (
                    <td key={key}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) => {
                          const next = new Map(changed);
                          next.set(key, event.currentTarget.checked);
                          setChanged(next);
                        }}
                        aria-label={`${role.key} ${permission.key}`}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RulesTab({ appKey }: { appKey: string }) {
  const rulesQuery = useQuery({
    queryKey: ["console", "app", appKey, "approval-rules"],
    queryFn: () => apiRequest<{ items?: ApprovalRuleItem[] }>(`/console/api/v1/apps/${appKey}/approval-rules`),
  });
  const rules = itemsFromPayload<ApprovalRuleItem>(rulesQuery.data);

  return (
    <DataTable
      data={rules}
      columns={[
        { header: "对象", cell: ({ row }) => `${row.original.target_type ?? "-"}:${row.original.target_key ?? "-"}` },
        { header: "审批人", cell: ({ row }) => safeJoin(row.original.approver_userids) },
        { header: "状态", cell: ({ row }) => <Badge tone={row.original.is_active ? "success" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge> },
      ]}
      emptyText={rulesQuery.isLoading ? "加载中" : "暂无审批规则"}
    />
  );
}

function CredentialsTab({ appKey }: { appKey: string }) {
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<SecretPayload | null>(null);
  const credentialsQuery = useQuery({
    queryKey: ["console", "app", appKey, "credentials"],
    queryFn: () => apiRequest<{ items?: CredentialItem[] }>(`/console/api/v1/apps/${appKey}/credentials`),
  });
  const credentials = itemsFromPayload<CredentialItem>(credentialsQuery.data);
  const createSecretMutation = useMutation({
    mutationFn: (kind: "static-tokens" | "oauth-clients") =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/${kind}`, {
        method: "POST",
        body: { name },
      }),
    onSuccess: (payload) => {
      setName("");
      setSecret(payload);
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "credentials"] });
    },
  });
  const rotateMutation = useMutation({
    mutationFn: (credentialId: number) =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/static-tokens/${credentialId}/rotate`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      setSecret(payload);
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "credentials"] });
    },
  });
  const disableMutation = useMutation({
    mutationFn: (credential: CredentialItem) => {
      const kind = credentialDisablePathSegment(credential.kind);
      return apiRequest(`/console/api/v1/apps/${appKey}/credentials/${kind}/${credential.id}/disable`, {
        method: "POST",
        body: {},
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "credentials"] }),
  });
  const secretEntries = Object.entries(secret?.one_time_secret ?? {}).filter(([key]) => key !== "kind");

  return (
    <section className="stack">
      <div className="inline-form">
        <Field label="凭据名称">
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} placeholder="integration primary" />
        </Field>
        <Button variant="primary" icon={<Plus size={16} />} disabled={!name} onClick={() => createSecretMutation.mutate("static-tokens")}>
          静态 token
        </Button>
        <Button icon={<KeyRound size={16} />} disabled={!name} onClick={() => createSecretMutation.mutate("oauth-clients")}>
          OAuth client
        </Button>
      </div>
      {createSecretMutation.error || rotateMutation.error || disableMutation.error ? (
        <StatusBanner
          tone="danger"
          title="凭据操作失败"
          message={((createSecretMutation.error ?? rotateMutation.error ?? disableMutation.error) as Error).message}
        />
      ) : null}
      <DataTable
        data={credentials}
        columns={[
          { header: "名称", accessorKey: "name" },
          { header: "类型", cell: ({ row }) => credentialKindLabel(row.original.kind) },
          { header: "client_id", cell: ({ row }) => row.original.client_id ? <code>{row.original.client_id}</code> : "-" },
          { header: "状态", cell: ({ row }) => <Badge tone={row.original.is_active ? "success" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge> },
          {
            header: "操作",
            cell: ({ row }) => (
              <div className="row-actions">
                {row.original.kind === "static_token" ? (
                  <Button variant="ghost" icon={<RotateCw size={14} />} onClick={() => rotateMutation.mutate(row.original.id)} aria-label="轮换" />
                ) : null}
                <Button variant="ghost" icon={<ShieldOff size={14} />} onClick={() => disableMutation.mutate(row.original)} aria-label="禁用" />
              </div>
            ),
          },
        ]}
        emptyText={credentialsQuery.isLoading ? "加载中" : "暂无凭据"}
      />
      {secret && secretEntries[0] ? (
        <SecretDialog
          title="一次性凭据"
          primaryLabel={secretEntries[0][0]}
          primaryValue={secretEntries[0][1]}
          secondaryLabel={secretEntries[1]?.[0]}
          secondaryValue={secretEntries[1]?.[1]}
          onClose={() => {
            setSecret(null);
            createSecretMutation.reset();
            rotateMutation.reset();
          }}
        />
      ) : null}
    </section>
  );
}

function QueryTestTab({ appKey }: { appKey: string }) {
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<QueryTestResult | null>(null);
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<QueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: userId, token },
      }),
    onSuccess: (payload) => {
      setResult(payload);
      setToken("");
    },
  });

  return (
    <section className="stack">
      <div className="inline-form">
        <Field label="用户 ID">
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} />
        </Field>
        <Field label="Bearer token">
          <TextInput type="password" value={token} onChange={(event) => setToken(event.currentTarget.value)} autoComplete="off" />
        </Field>
        <Button variant="primary" icon={<Play size={16} />} disabled={!userId || !token} onClick={() => testMutation.mutate()}>
          执行联调
        </Button>
      </div>
      {testMutation.error ? <StatusBanner tone="danger" title="联调失败" message={(testMutation.error as Error).message} /> : null}
      {result ? (
        <>
          <Toast tone="success" message={result.allowed ? "权限查询命中授权" : "查询成功，无授权命中"} />
          <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
        </>
      ) : null}
    </section>
  );
}

function GuideTab({ appKey }: { appKey: string }) {
  const guideQuery = useQuery({
    queryKey: ["console", "app", appKey, "integration-guide"],
    queryFn: () => apiRequest<IntegrationGuide>(`/console/api/v1/apps/${appKey}/integration-guide`),
  });
  const endpoint = guideQuery.data?.permission_query_endpoint ?? `/api/v1/apps/${appKey}/users/{user_id}/permissions`;
  const curl = `curl -H "Authorization: Bearer $APP_TOKEN" "${endpoint}"`;
  const ts = `await fetch("${endpoint}", {\n  headers: { Authorization: \`Bearer \${appToken}\` },\n});`;

  return (
    <section className="stack">
      <DataTable
        data={guideQuery.data?.credential_modes ?? []}
        columns={[
          { header: "模式", accessorKey: "mode" },
          { header: "活跃数量", accessorKey: "active_count" },
        ]}
        emptyText={guideQuery.isLoading ? "加载中" : "暂无活跃凭据"}
      />
      <CodeBlock language="curl" code={curl} />
      <CodeBlock language="typescript" code={ts} />
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function flattenGroups(groups: PermissionGroupItem[]): PermissionGroupItem[] {
  return groups.flatMap((group) => [
    group,
    ...flattenGroups((group.children ?? []).filter(isPermissionGroup)),
  ]);
}

function isPermissionGroup(item: PermissionGroupItem | PermissionItem): item is PermissionGroupItem {
  return "type" in item && item.type === "group";
}

function safeJoin(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}

function credentialKindLabel(kind: string): string {
  switch (kind) {
    case "static_token":
      return "静态 token";
    case "oauth_client":
      return "OAuth client";
    default:
      return kind;
  }
}
