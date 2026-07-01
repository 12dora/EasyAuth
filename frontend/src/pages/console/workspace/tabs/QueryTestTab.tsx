import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { DataTable } from "../../../../components/DataTable";
import { Field, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { Toast } from "../../../../components/Toast";
import { apiRequest } from "../../../../lib/api";
import type { QueryTestResult } from "../../../../lib/domain";

type QueryTestGroup = { key?: string; name?: string; source?: string; snapshot_version?: string };
type QueryTestGrant = {
  permission?: string;
  scope?: string;
  source_type?: string;
  source_key?: string;
  name?: string;
  snapshot_version?: string;
  grant_type?: string;
};
type StructuredQueryTestResult = QueryTestResult & {
  source?: string;
  snapshot_version?: string;
  groups?: QueryTestGroup[];
  grants?: QueryTestGrant[];
};

export function QueryTestTab({ appKey }: { appKey: string }) {
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<StructuredQueryTestResult | null>(null);
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<StructuredQueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
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
          <div className="metric-grid">
            <div className="metric-card">
              <span className="metric-label">source</span>
              <strong>来源：{result.source ?? "-"}</strong>
            </div>
            <div className="metric-card">
              <span className="metric-label">snapshot_version</span>
              <strong>快照版本：{result.snapshot_version ?? result.version ?? "-"}</strong>
            </div>
          </div>
          <DataTable
            data={result.groups ?? []}
            columns={[
              { header: "授权组", cell: ({ row }) => row.original.key ?? "-" },
              { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
              { header: "来源", cell: ({ row }) => row.original.source ?? "-" },
              { header: "快照版本", cell: ({ row }) => row.original.snapshot_version ?? result.snapshot_version ?? "-" },
            ]}
            emptyText="暂无授权组"
          />
          <DataTable
            data={result.grants ?? []}
            columns={[
              { header: "授权项", cell: ({ row }) => row.original.permission ?? "-" },
              { header: "Scope", cell: ({ row }) => row.original.scope ?? "-" },
              { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
              { header: "类型", cell: ({ row }) => row.original.grant_type ?? "-" },
              {
                header: "来源",
                cell: ({ row }) =>
                  row.original.source_key
                    ? `${row.original.source_type ?? "-"}:${row.original.source_key}`
                    : row.original.source_type ?? "-",
              },
              { header: "快照版本", cell: ({ row }) => row.original.snapshot_version ?? result.snapshot_version ?? "-" },
            ]}
            emptyText="暂无授权项"
          />
          <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
        </>
      ) : null}
    </section>
  );
}
