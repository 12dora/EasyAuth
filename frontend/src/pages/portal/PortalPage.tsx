import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronRight, Send } from "lucide-react";
import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
import { useLocation } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { Toast } from "../../components/Toast";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { PermissionGroupItem, PermissionItem, PortalGrant, PortalRequest, PortalRequestCatalog } from "../../lib/domain";
import { queryClient } from "../../lib/query";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../lib/status";

type PortalView = "grants" | "request" | "requests" | "expiring";

export function PortalPage() {
  const location = useLocation();
  const view = portalViewFromPath(location.pathname);

  return (
    <>
      <PageHeader
        eyebrow="Portal"
        title={viewTitle(view)}
        description="按当前员工 session 查看授权、申请记录和到期提醒。"
      />
      {view === "grants" ? <GrantTable endpoint="/portal/api/v1/me/grants" emptyText="暂无当前授权" /> : null}
      {view === "expiring" ? <GrantTable endpoint="/portal/api/v1/me/grants/expiring" emptyText="暂无即将过期授权" /> : null}
      {view === "requests" ? <RequestTable /> : null}
      {view === "request" ? <AccessRequestForm /> : null}
    </>
  );
}

function GrantTable({ endpoint, emptyText }: { endpoint: string; emptyText: string }) {
  const query = useQuery({
    queryKey: ["portal", endpoint],
    queryFn: () => apiRequest<{ items?: PortalGrant[]; data?: PortalGrant[] }>(endpoint),
  });
  const grants = itemsFromPayload<PortalGrant>(query.data);
  const columns: ColumnDef<PortalGrant>[] = [
    {
      header: "应用",
      cell: ({ row }) => (
        <div className="table-title">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: "角色", cell: ({ row }) => join(row.original.role_names ?? row.original.roles) },
    { header: "权限", cell: ({ row }) => join(row.original.permissions) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { header: "版本", cell: ({ row }) => row.original.version ?? "-" },
    { header: "过期时间", cell: ({ row }) => formatDateTime(row.original.grant_expires_at) },
  ];

  return (
    <>
      {query.error ? <StatusBanner tone="danger" title="授权加载失败" message={(query.error as Error).message} /> : null}
      <DataTable data={grants} columns={columns} emptyText={query.isLoading ? "加载中" : emptyText} />
    </>
  );
}

function RequestTable() {
  const query = useQuery({
    queryKey: ["portal", "requests"],
    queryFn: () => apiRequest<{ items?: PortalRequest[]; data?: PortalRequest[] }>("/portal/api/v1/me/access-requests"),
  });
  const requests = itemsFromPayload<PortalRequest>(query.data);
  const columns: ColumnDef<PortalRequest>[] = [
    {
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={badgeToneForAccessRequestStatus(row.original.status)}>
          {row.original.status_label ?? accessRequestStatusLabel(row.original.status)}
        </Badge>
      ),
    },
    { header: "应用", cell: ({ row }) => row.original.app_name ?? row.original.app_key ?? "-" },
    { header: "角色", cell: ({ row }) => join(row.original.role_names ?? row.original.roles) },
    { header: "权限", cell: ({ row }) => join(row.original.permissions) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { header: "提交时间", cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: "原因", cell: ({ row }) => row.original.reason ?? "-" },
  ];

  return (
    <>
      {query.error ? <StatusBanner tone="danger" title="申请记录加载失败" message={(query.error as Error).message} /> : null}
      <DataTable data={requests} columns={columns} emptyText={query.isLoading ? "加载中" : "暂无申请记录"} />
    </>
  );
}

function AccessRequestForm() {
  const [appKey, setAppKey] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<string[]>([]);
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const [grantType, setGrantType] = useState<"permanent" | "timed">("permanent");
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");
  const catalogQuery = useQuery({
    queryKey: ["portal", "request-catalog"],
    queryFn: () => apiRequest<PortalRequestCatalog>("/portal/api/v1/request-catalog"),
  });
  const apps = catalogQuery.data?.apps ?? [];
  const roles = (catalogQuery.data?.roles ?? []).filter((role) => !appKey || role.app_key === appKey);
  const permissionGroups = useMemo(
    () => filterGroupsByApp(catalogQuery.data?.permission_groups ?? [], appKey),
    [appKey, catalogQuery.data],
  );
  const ungroupedPermissions = useMemo(
    () => (catalogQuery.data?.ungrouped_permissions ?? []).filter((permission) => !appKey || permission.app_key === appKey),
    [appKey, catalogQuery.data],
  );
  const visiblePermissionKeys = useMemo(
    () => collectPermissionKeys(permissionGroups, ungroupedPermissions),
    [permissionGroups, ungroupedPermissions],
  );
  const submitMutation = useMutation({
    mutationFn: () =>
      apiRequest("/portal/api/v1/me/access-requests", {
        method: "POST",
        body: {
          app_key: appKey,
          request_type: "grant",
          role_keys: roleKey ? [roleKey] : [],
          permission_keys: selectedPermissionKeys,
          grant_type: grantType,
          grant_expires_at: grantType === "timed" && expiresAt ? new Date(expiresAt).toISOString() : null,
          reason,
        },
      }),
    onSuccess: () => {
      setRoleKey("");
      setSelectedPermissionKeys([]);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["portal", "requests"] });
    },
  });
  const hasTarget = Boolean(roleKey || selectedPermissionKeys.length > 0);
  const canSubmit = Boolean(appKey && hasTarget && reason && (grantType === "permanent" || expiresAt) && !submitMutation.isPending);

  function togglePermission(key: string) {
    setSelectedPermissionKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }

  function toggleGroup(key: string) {
    setExpandedGroupKeys((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }

  return (
    <section className="form-surface">
      <div className="form-grid">
        <Field label="应用" hint="来自员工门户可申请目录。">
          <SelectInput
            value={appKey}
            onChange={(event) => {
              setAppKey(event.currentTarget.value);
              setRoleKey("");
              setSelectedPermissionKeys([]);
              setExpandedGroupKeys([]);
            }}
          >
            <option value="">选择应用</option>
            {apps.map((app) => (
              <option key={app.app_key} value={app.app_key}>
                {app.name} ({app.app_key})
              </option>
            ))}
          </SelectInput>
        </Field>
        <Field label="角色" hint="仅展示 active、requestable 且有审批规则的角色。">
          <SelectInput value={roleKey} onChange={(event) => setRoleKey(event.currentTarget.value)} disabled={!appKey}>
            <option value="">不选择角色</option>
            {roles.map((role) => (
              <option key={`${role.app_key}:${role.key}`} value={role.key}>
                {role.name} ({role.key})
              </option>
            ))}
          </SelectInput>
        </Field>
        <div className="field">
          <span className="field-label">直接权限</span>
          <PermissionSelector
            appKey={appKey}
            groups={permissionGroups}
            ungroupedPermissions={ungroupedPermissions}
            selectedKeys={selectedPermissionKeys}
            expandedGroupKeys={expandedGroupKeys}
            loading={catalogQuery.isLoading}
            errorMessage={catalogQuery.error ? (catalogQuery.error as Error).message : ""}
            onTogglePermission={togglePermission}
            onToggleGroup={toggleGroup}
          />
          <span className="field-hint">
            {appKey ? `已选 ${selectedPermissionKeys.length} 项直接权限，可留空。` : "请先选择应用后再选择直接权限。"}
          </span>
        </div>
        <Field label="授权期限">
          <SelectInput value={grantType} onChange={(event) => setGrantType(event.currentTarget.value as "permanent" | "timed")}>
            <option value="permanent">长期</option>
            <option value="timed">限时</option>
          </SelectInput>
        </Field>
        {grantType === "timed" ? (
          <Field label="过期时间">
            <TextInput type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.currentTarget.value)} />
          </Field>
        ) : null}
        <Field label="申请原因">
          <TextArea rows={4} value={reason} onChange={(event) => setReason(event.currentTarget.value)} />
        </Field>
      </div>
      {catalogQuery.error ? <StatusBanner tone="danger" title="申请目录加载失败" message={(catalogQuery.error as Error).message} /> : null}
      {!catalogQuery.isLoading && appKey && visiblePermissionKeys.length === 0 ? (
        <StatusBanner tone="warning" title="未发现可选直接权限" message="当前应用没有返回权限目录，可仅按角色发起申请。" />
      ) : null}
      <div className="panel-toolbar">
        <Button
          variant="primary"
          icon={<Send size={16} />}
          disabled={!canSubmit}
          onClick={() => submitMutation.mutate()}
        >
          提交申请
        </Button>
      </div>
      {submitMutation.error ? <StatusBanner tone="danger" title="提交失败" message={(submitMutation.error as Error).message} /> : null}
      {submitMutation.isSuccess ? <Toast message="申请已提交" /> : null}
    </section>
  );
}

function portalViewFromPath(pathname: string): PortalView {
  if (pathname.endsWith("/request")) {
    return "request";
  }
  if (pathname.endsWith("/requests")) {
    return "requests";
  }
  if (pathname.endsWith("/expiring")) {
    return "expiring";
  }
  return "grants";
}

function viewTitle(view: PortalView): string {
  switch (view) {
    case "request":
      return "申请权限";
    case "requests":
      return "我的申请";
    case "expiring":
      return "即将过期";
    default:
      return "我的权限";
  }
}

function join(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}

interface PermissionSelectorProps {
  appKey: string;
  groups: PermissionGroupItem[];
  ungroupedPermissions: PermissionItem[];
  selectedKeys: string[];
  expandedGroupKeys: string[];
  loading: boolean;
  errorMessage: string;
  onTogglePermission: (key: string) => void;
  onToggleGroup: (key: string) => void;
}

function PermissionSelector({
  appKey,
  groups,
  ungroupedPermissions,
  selectedKeys,
  expandedGroupKeys,
  loading,
  errorMessage,
  onTogglePermission,
  onToggleGroup,
}: PermissionSelectorProps) {
  if (!appKey) {
    return <div className="permission-selector-empty">选择应用后加载权限目录。</div>;
  }
  if (loading) {
    return <div className="permission-selector-empty">权限目录加载中。</div>;
  }
  if (errorMessage) {
    return <div className="permission-selector-empty">权限目录加载失败：{errorMessage}</div>;
  }

  return (
    <div className="permission-selector">
      <table className="permission-table" aria-label="权限选择">
        <thead>
          <tr>
            <th>权限</th>
            <th>Key</th>
            <th>选择</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <PermissionGroupRows
              key={group.key}
              group={group}
              depth={0}
              selectedKeys={selectedKeys}
              expandedGroupKeys={expandedGroupKeys}
              onTogglePermission={onTogglePermission}
              onToggleGroup={onToggleGroup}
            />
          ))}
          {ungroupedPermissions.map((permission) => (
            <PermissionRow
              key={permission.key}
              permission={permission}
              depth={0}
              checked={selectedKeys.includes(permission.key)}
              onToggle={onTogglePermission}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PermissionGroupRows({
  group,
  depth,
  selectedKeys,
  expandedGroupKeys,
  onTogglePermission,
  onToggleGroup,
}: {
  group: PermissionGroupItem;
  depth: number;
  selectedKeys: string[];
  expandedGroupKeys: string[];
  onTogglePermission: (key: string) => void;
  onToggleGroup: (key: string) => void;
}) {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = collectGroupPermissions(group);
  const isExpanded = expandedGroupKeys.includes(group.key);
  const selectedCount = childPermissions.filter((permission) => selectedKeys.includes(permission.key)).length;

  return (
    <>
      <tr className="permission-group-row">
        <td>
          <button
            type="button"
            className="permission-group-toggle"
            onClick={() => onToggleGroup(group.key)}
            aria-expanded={isExpanded}
            aria-label={`${isExpanded ? "收起" : "展开"} ${group.name}`}
            style={{ "--permission-depth": depth } as CSSProperties}
          >
            <ChevronRight size={16} className={isExpanded ? "expanded" : ""} />
            <span className="permission-group-title">{group.name}</span>
            <span className="permission-group-count">
              {selectedCount}/{childPermissions.length}
            </span>
          </button>
        </td>
        <td>
          <code>{group.key}</code>
        </td>
        <td aria-label="权限组不可直接选择">-</td>
      </tr>
      {isExpanded ? (
        <>
          {group.permissions?.map((permission) => (
            <PermissionRow
              key={permission.key}
              permission={permission}
              depth={depth + 1}
              checked={selectedKeys.includes(permission.key)}
              onToggle={onTogglePermission}
            />
          ))}
          {childGroups.map((childGroup) => (
            <PermissionGroupRows
              key={childGroup.key}
              group={childGroup}
              depth={depth + 1}
              selectedKeys={selectedKeys}
              expandedGroupKeys={expandedGroupKeys}
              onTogglePermission={onTogglePermission}
              onToggleGroup={onToggleGroup}
            />
          ))}
        </>
      ) : null}
    </>
  );
}

function PermissionRow({
  permission,
  depth,
  checked,
  onToggle,
}: {
  permission: PermissionItem;
  depth: number;
  checked: boolean;
  onToggle: (key: string) => void;
}) {
  return (
    <tr className="permission-row">
      <td>
        <span className="permission-name" style={{ "--permission-depth": depth } as CSSProperties}>
          {permission.name}
        </span>
      </td>
      <td>
        <code>{permission.key}</code>
      </td>
      <td>
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(permission.key)}
          aria-label={`选择 ${permission.key}`}
        />
      </td>
    </tr>
  );
}

function collectPermissionKeys(groups: PermissionGroupItem[], ungroupedPermissions: PermissionItem[]): string[] {
  return [...collectPermissions(groups).map((permission) => permission.key), ...ungroupedPermissions.map((permission) => permission.key)];
}

function collectPermissions(groups: PermissionGroupItem[]): PermissionItem[] {
  return groups.flatMap((group) => collectGroupPermissions(group));
}

function collectGroupPermissions(group: PermissionGroupItem): PermissionItem[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  return [...(group.permissions ?? []), ...childGroups.flatMap((childGroup) => collectGroupPermissions(childGroup))];
}

function isPermissionGroupItem(item: PermissionGroupItem | PermissionItem): item is PermissionGroupItem {
  return "type" in item && item.type === "group";
}

function filterGroupsByApp(groups: PermissionGroupItem[], appKey: string): PermissionGroupItem[] {
  if (!appKey) {
    return [];
  }
  return groups
    .filter((group) => !group.app_key || group.app_key === appKey)
    .map((group) => ({
      ...group,
      children: (group.children ?? [])
        .map((child) => (isPermissionGroupItem(child) ? filterGroupByApp(child, appKey) : filterPermissionByApp(child, appKey)))
        .filter((child): child is PermissionGroupItem | PermissionItem => Boolean(child)),
      permissions: (group.permissions ?? []).filter((permission) => !permission.app_key || permission.app_key === appKey),
    }));
}

function filterGroupByApp(group: PermissionGroupItem, appKey: string): PermissionGroupItem | null {
  if (group.app_key && group.app_key !== appKey) {
    return null;
  }
  return {
    ...group,
    children: (group.children ?? [])
      .map((child) => (isPermissionGroupItem(child) ? filterGroupByApp(child, appKey) : filterPermissionByApp(child, appKey)))
      .filter((child): child is PermissionGroupItem | PermissionItem => Boolean(child)),
    permissions: (group.permissions ?? []).filter((permission) => !permission.app_key || permission.app_key === appKey),
  };
}

function filterPermissionByApp(permission: PermissionItem, appKey: string): PermissionItem | null {
  if (permission.app_key && permission.app_key !== appKey) {
    return null;
  }
  return permission;
}
