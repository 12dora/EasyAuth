import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCcw } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { AppListPayload, AppSummary } from "../../lib/domain";
import { formatDateTime, readinessLabel, readinessTone } from "../../lib/status";

export function ConsoleAppList() {
  const appsQuery = useQuery({
    queryKey: ["console", "apps"],
    queryFn: () => apiRequest<AppListPayload>("/console/api/v1/apps"),
  });
  const apps = itemsFromPayload<AppSummary>(appsQuery.data);

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
          <Button icon={<RefreshCcw size={16} />} onClick={() => void appsQuery.refetch()}>
            刷新
          </Button>
        }
      />
      {appsQuery.error ? (
        <StatusBanner tone="danger" title="应用加载失败" message={(appsQuery.error as Error).message} />
      ) : null}
      <DataTable data={apps} columns={columns} emptyText={appsQuery.isLoading ? "加载中" : "暂无可见应用"} />
    </>
  );
}

function safeJoin(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}
