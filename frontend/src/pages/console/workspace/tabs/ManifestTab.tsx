import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Download, Eye, FileUp, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
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
  const versionColumns: ColumnDef<ManifestVersion>[] = [
    { header: "版本", cell: ({ row }) => row.original.catalog_version ?? row.original.version ?? "-" },
    { header: "导入时间", cell: ({ row }) => row.original.imported_at ?? row.original.created_at ?? "-" },
    { header: "导入人", cell: ({ row }) => row.original.imported_by ?? "-" },
  ];
  const versionsTable = useReactTable({
    data: versions,
    columns: versionColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
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
    <section className="space-y-6">
      <PanelSurface className="flex flex-wrap items-center gap-2">
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
          上传文件
        </Button>
        <Button
          icon={<Download size={16} />}
          onClick={() => {
            window.location.assign(`/console/api/v1/apps/${appKey}/manifest`);
          }}
        >
          导出清单
        </Button>
      </PanelSurface>
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
      <div className="flex flex-wrap items-center gap-2">
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
      {previewMutation.error ? <StatusBanner tone="signal" title="Manifest 预览失败" message={(previewMutation.error as Error).message} /> : null}
      {importMutation.error ? <StatusBanner tone="signal" title="Manifest 导入失败" message={(importMutation.error as Error).message} /> : null}
      {catalogVersion ? <Toast tone="evergreen" message={`当前目录版本：${catalogVersion}`} /> : null}
      {preview ? <ManifestDiffView preview={preview} /> : null}
      <TableFrame>
        <TableRoot>
          <TableHead>
            {versionsTable.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
                ))}
              </TableRow>
            ))}
          </TableHead>
          <TableBody>
            {versionsTable.getRowModel().rows.length > 0 ? (
              versionsTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={versionColumns.length}>
                  {versionsQuery.isLoading ? "加载中" : "暂无版本历史"}
                </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={versionsTable} />
      </TableFrame>
    </section>
  );
}

function ManifestDiffView({ preview }: { preview: ManifestPreviewPayload }) {
  const diff = preview.diff ?? diffFromChanges(preview.changes ?? []);
  const sections = [
    { title: "新增", tone: "evergreen" as const, items: diff.added ?? [] },
    { title: "变更", tone: "amber" as const, items: diff.changed ?? [] },
    { title: "移除", tone: "signal" as const, items: diff.removed ?? [] },
  ];

  return (
    <div className="space-y-4">
      {sections.map((section) => (
        <PanelSurface className="space-y-3" key={section.title}>
          <div className="flex items-center justify-between gap-3">
            <Badge tone={section.tone}>{section.title}</Badge>
          </div>
          <ManifestDiffTable items={section.items} />
        </PanelSurface>
      ))}
    </div>
  );
}

function ManifestDiffTable({ items }: { items: ManifestDiffItem[] }) {
  const columns: ColumnDef<ManifestDiffItem>[] = [
    { header: "对象", cell: ({ row }) => `${row.original.type ?? "-"}:${row.original.key ?? "-"}` },
    { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
    { header: "详情", cell: ({ row }) => <CodeBlock language="json" code={JSON.stringify({ before: row.original.before, after: row.original.after }, null, 2)} /> },
  ];
  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <TableFrame>
      <TableRoot>
        <TableHead>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
              ))}
            </TableRow>
          ))}
        </TableHead>
        <TableBody>
          {table.getRowModel().rows.length > 0 ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={columns.length}>
                无差异
              </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} />
    </TableFrame>
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
