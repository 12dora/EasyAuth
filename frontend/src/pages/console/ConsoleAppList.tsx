import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCcw } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload, AppSummary } from "../../lib/domain";
import { formatDateTime, readinessLabel, readinessTone } from "../../lib/status";

export function ConsoleAppList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const isAdmin = isConsoleAdmin();
  const appsQuery = useQuery({
    queryKey: ["console", "apps"],
    queryFn: () => apiRequest<AppListPayload>("/console/api/v1/apps"),
  });
  const apps = itemsFromPayload<AppSummary>(appsQuery.data);
  const createMutation = useMutation({
    mutationFn: (payload: AppCreateFormPayload) =>
      apiRequest<AppListPayload>("/console/api/v1/apps", {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      const appKey = payload.app?.app_key;
      if (appKey) {
        void navigate(`/console/apps/${appKey}`);
      }
    },
  });

  const columns: ColumnDef<AppSummary>[] = [
    {
      header: "应用",
      cell: ({ row }) => (
        <div className="table-title">
          <strong>{row.original.name}</strong>
          <code>{row.original.app_key}</code>
        </div>
      ),
    },
    {
      header: "负责人",
      cell: ({ row }) => <span>{safeJoin(row.original.owners)}</span>,
    },
    {
      header: "配置",
      cell: ({ row }) => (
        <Badge tone={readinessTone(row.original.configuration_status)}>
          {readinessLabel(row.original.configuration_status)}
        </Badge>
      ),
    },
    {
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "success" : "neutral"}>
          {row.original.is_active ? "启用" : "停用"}
        </Badge>
      ),
    },
    {
      header: "更新时间",
      cell: ({ row }) => formatDateTime(row.original.updated_at),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Link className="row-action" to={`/console/apps/${row.original.app_key}`}>
          <span>进入</span>
          <ArrowRight size={15} />
        </Link>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Console"
        title="应用列表"
        description="查看可管理应用、配置完整性和接入入口。"
        actions={
          <>
            {isAdmin ? (
              <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
                新建应用
              </Button>
            ) : null}
            <Button icon={<RefreshCcw size={16} />} onClick={() => void appsQuery.refetch()}>
              刷新
            </Button>
          </>
        }
      />
      {appsQuery.error ? (
        <StatusBanner tone="danger" title="应用加载失败" message={(appsQuery.error as Error).message} />
      ) : null}
      <DataTable data={apps} columns={columns} emptyText={appsQuery.isLoading ? "加载中" : "暂无可见应用"} />
      {createDialogOpen && isAdmin ? (
        <CreateAppDialog
          errorMessage={createMutation.error ? (createMutation.error as Error).message : ""}
          isSubmitting={createMutation.isPending}
          onClose={() => setCreateDialogOpen(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />
      ) : null}
    </>
  );
}

function safeJoin(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}

interface AppCreateFormPayload {
  app_key: string;
  name: string;
  description: string;
  owner_user_ids: string[];
  developer_user_ids: string[];
  is_active: boolean;
}

function CreateAppDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: AppCreateFormPayload) => void;
}) {
  const [appKey, setAppKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ownerUserIds, setOwnerUserIds] = useState("");
  const [developerUserIds, setDeveloperUserIds] = useState("");
  const [isActive, setIsActive] = useState(true);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      app_key: appKey.trim(),
      name: name.trim(),
      description: description.trim(),
      owner_user_ids: splitUserIds(ownerUserIds),
      developer_user_ids: splitUserIds(developerUserIds),
      is_active: isActive,
    });
  };

  return (
    <Dialog
      title="新建应用"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            取消
          </Button>
          <Button form="create-app-form" type="submit" variant="primary" disabled={isSubmitting}>
            创建
          </Button>
        </>
      }
    >
      <form id="create-app-form" className="form-grid" onSubmit={submit}>
        <Field label="app_key">
          <TextInput value={appKey} onChange={(event) => setAppKey(event.currentTarget.value)} required />
        </Field>
        <Field label="名称">
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label="描述">
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <Field label="Owner 用户 ID" hint="多个用户用逗号或换行分隔。">
          <TextInput
            aria-label="Owner 用户 ID"
            value={ownerUserIds}
            onChange={(event) => setOwnerUserIds(event.currentTarget.value)}
          />
        </Field>
        <Field label="Developer 用户 ID" hint="多个用户用逗号或换行分隔。">
          <TextInput
            aria-label="Developer 用户 ID"
            value={developerUserIds}
            onChange={(event) => setDeveloperUserIds(event.currentTarget.value)}
          />
        </Field>
        <label className="field">
          <span className="field-label">状态</span>
          <span>
            <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.currentTarget.checked)} /> 启用应用
          </span>
        </label>
        {errorMessage ? <StatusBanner tone="danger" title="创建失败" message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

function splitUserIds(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isConsoleAdmin(): boolean {
  const role =
    document.body.dataset.currentUserRole ??
    document.documentElement.dataset.currentUserRole ??
    document.getElementById("easyauth-root")?.dataset.currentUserRole ??
    "";
  return role === "EasyAuth Admins";
}
