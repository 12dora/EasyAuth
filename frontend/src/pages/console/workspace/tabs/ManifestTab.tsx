import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, FileUp, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { DataTable } from "../../../../components/DataTable";
import { Field, TextArea } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { Toast } from "../../../../components/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";

type ManifestDiffItem = {
  type?: string;
  key?: string;
  name?: string;
  before?: unknown;
  after?: unknown;
};

type ManifestPreviewPayload = {
  diff?: {
    added?: ManifestDiffItem[];
    changed?: ManifestDiffItem[];
    removed?: ManifestDiffItem[];
  };
  changes?: Array<{ action?: string; key?: string; parent_key?: string }>;
  preview_id?: string;
};

type ManifestImportPayload = {
  catalog_version?: string | number;
  template_version?: string | number;
  version?: string | number | { version?: string | number };
};

type ManifestVersion = {
  version?: string;
  catalog_version?: string;
  imported_at?: string;
  created_at?: string;
  imported_by?: string;
};

export function ManifestTab({ appKey }: { appKey: string }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<ManifestPreviewPayload | null>(null);
  const [catalogVersion, setCatalogVersion] = useState<string | null>(null);
  const versionsQueryKey = ["console", "app", appKey, "manifest-versions"];
  const versionsQuery = useQuery({
    queryKey: versionsQueryKey,
    queryFn: () => apiRequest<{ items?: ManifestVersion[] }>(`/console/api/v1/apps/${appKey}/permission-template-versions`),
  });
  const versions = itemsFromPayload<ManifestVersion>(versionsQuery.data);
  const previewMutation = useMutation({
    mutationFn: () =>
      apiRequest<ManifestPreviewPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/preview`, {
        method: "POST",
        body: { template_format: "json", template: content },
      }),
    onSuccess: (payload) => setPreview(payload),
  });
  const importMutation = useMutation({
    mutationFn: () =>
      apiRequest<ManifestImportPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/${preview?.preview_id ?? ""}/confirm`, {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setCatalogVersion(String(payload.catalog_version ?? payload.template_version ?? versionLabel(payload.version) ?? ""));
      await queryClient.invalidateQueries({ queryKey: versionsQueryKey });
    },
  });

  return (
    <section className="stack">
      <div className="inline-actions">
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.yaml,.yml,application/json,text/yaml,text/plain"
          className="sr-only"
          aria-label="上传 Manifest 文件"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (!file) {
              return;
            }
            void file.text().then(setContent);
          }}
        />
        <Button icon={<FileUp size={16} />} onClick={() => fileInputRef.current?.click()}>
          上传
        </Button>
        <Button
          icon={<Download size={16} />}
          onClick={() => {
            window.location.assign(`/console/api/v1/apps/${appKey}/manifest`);
          }}
        >
          导出
        </Button>
      </div>
      <Field label="Manifest 内容" hint="支持粘贴 JSON 或 YAML；上传文件后会填充到这里。">
        <TextArea
          aria-label="Manifest 内容"
          rows={10}
          value={content}
          onChange={(event) => {
            setContent(event.currentTarget.value);
          }}
        />
      </Field>
      <div className="inline-actions">
        <Button variant="primary" icon={<Eye size={16} />} disabled={!content || previewMutation.isPending} onClick={() => previewMutation.mutate()}>
          预览差异
        </Button>
        <Button
          variant="primary"
          icon={<UploadCloud size={16} />}
          disabled={!preview?.preview_id || importMutation.isPending}
          onClick={() => importMutation.mutate()}
        >
          确认导入
        </Button>
      </div>
      {previewMutation.error ? <StatusBanner tone="danger" title="Manifest 预览失败" message={(previewMutation.error as Error).message} /> : null}
      {importMutation.error ? <StatusBanner tone="danger" title="Manifest 导入失败" message={(importMutation.error as Error).message} /> : null}
      {catalogVersion ? <Toast message={`当前目录版本：${catalogVersion}`} /> : null}
      {preview ? <ManifestDiffView preview={preview} /> : null}
      <DataTable
        data={versions}
        columns={[
          { header: "版本", cell: ({ row }) => row.original.catalog_version ?? row.original.version ?? "-" },
          { header: "导入时间", cell: ({ row }) => row.original.imported_at ?? row.original.created_at ?? "-" },
          { header: "导入人", cell: ({ row }) => row.original.imported_by ?? "-" },
        ]}
        emptyText={versionsQuery.isLoading ? "加载中" : "暂无版本历史"}
      />
    </section>
  );
}

function ManifestDiffView({ preview }: { preview: ManifestPreviewPayload }) {
  const diff = preview.diff ?? diffFromChanges(preview.changes ?? []);
  const sections = [
    { title: "新增", tone: "success" as const, items: diff.added ?? [] },
    { title: "变更", tone: "warning" as const, items: diff.changed ?? [] },
    { title: "移除", tone: "danger" as const, items: diff.removed ?? [] },
  ];

  return (
    <div className="stack">
      {sections.map((section) => (
        <div className="panel" key={section.title}>
          <div className="section-heading">
            <Badge tone={section.tone}>{section.title}</Badge>
          </div>
          <DataTable
            data={section.items}
            columns={[
              { header: "对象", cell: ({ row }) => `${row.original.type ?? "-"}:${row.original.key ?? "-"}` },
              { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
              { header: "详情", cell: ({ row }) => <CodeBlock language="json" code={JSON.stringify({ before: row.original.before, after: row.original.after }, null, 2)} /> },
            ]}
            emptyText="无差异"
          />
        </div>
      ))}
    </div>
  );
}

function diffFromChanges(changes: Array<{ action?: string; key?: string; parent_key?: string }>): NonNullable<ManifestPreviewPayload["diff"]> {
  return {
    added: changes.filter((change) => change.action?.startsWith("create")).map(changeItem),
    changed: changes.filter((change) => change.action?.startsWith("update")).map(changeItem),
    removed: changes.filter((change) => change.action?.startsWith("deactivate")).map(changeItem),
  };
}

function changeItem(change: { action?: string; key?: string; parent_key?: string }): ManifestDiffItem {
  return {
    type: change.action,
    key: change.key,
    name: change.parent_key,
  };
}

function versionLabel(version: ManifestImportPayload["version"]): string | number | undefined {
  if (version === undefined || version === null) {
    return undefined;
  }
  if (typeof version === "object") {
    return version.version;
  }
  return version;
}
