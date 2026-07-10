import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Download, Eye, FileUp, Pencil, RefreshCcw, Save, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../../components/ui/TablePrimitives";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { Field, TextArea } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { JsonObject, ListPayload } from "../../../../lib/api";

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

type ManifestPreviewBinding = {
  payload: ManifestPreviewPayload;
  contentFingerprint: string;
  generation: number;
};

type ManifestImportPayload = {
  catalog_version?: string | number;
  template_version?: string | number;
};

type ManifestVersion = {
  version?: string;
  catalog_version?: string;
  imported_at?: string;
  created_at?: string;
  imported_by?: string;
};

export function ManifestTab({ appKey }: { appKey: string }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const contentRef = useRef("");
  const contentGenerationRef = useRef(0);
  const previewRequestRef = useRef(0);
  const fileReadRef = useRef(0);
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<ManifestPreviewBinding | null>(null);
  const [versionsPagination, setVersionsPagination] = useState({ pageIndex: 0, pageSize: 20 });
  const versionsQueryPrefix = ["console", "app", appKey, "manifest-versions"] as const;
  const versionsQueryKey = [...versionsQueryPrefix, versionsPagination.pageIndex, versionsPagination.pageSize];
  const versionsQuery = useQuery({
    queryKey: versionsQueryKey,
    queryFn: () =>
      apiRequest<ListPayload<ManifestVersion>>(
        `/console/api/v1/apps/${appKey}/permission-template-versions?page=${versionsPagination.pageIndex + 1}&page_size=${versionsPagination.pageSize}`,
      ),
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
    manualPagination: true,
    pageCount: versionsQuery.data?.pagination?.total_pages ?? 1,
    state: { pagination: versionsPagination },
    onPaginationChange: setVersionsPagination,
  });
  const previewMutation = useMutation({
    mutationFn: ({ contentSnapshot }: { contentSnapshot: string; contentFingerprint: string; generation: number; requestId: number }) =>
      apiRequest<ManifestPreviewPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/preview`, {
        method: "POST",
        body: { template_format: "json", template: contentSnapshot },
      }),
    onSuccess: (payload, variables) => {
      if (
        variables.requestId !== previewRequestRef.current ||
        variables.generation !== contentGenerationRef.current ||
        variables.contentFingerprint !== manifestContentFingerprint(contentRef.current)
      ) {
        return;
      }
      setPreview({ payload, contentFingerprint: variables.contentFingerprint, generation: variables.generation });
    },
    onError: (error: Error, variables) => {
      if (variables.requestId !== previewRequestRef.current || variables.generation !== contentGenerationRef.current) {
        return;
      }
      toast.error("Manifest 预览失败", error.message);
    },
  });
  const importMutation = useMutation({
    mutationFn: ({ previewId, contentFingerprint, generation }: { previewId: string; contentFingerprint: string; generation: number }) => {
      if (generation !== contentGenerationRef.current || contentFingerprint !== manifestContentFingerprint(contentRef.current)) {
        throw new Error("Manifest 内容已变化，请重新预览后再导入。");
      }
      return apiRequest<ManifestImportPayload>(`/console/api/v1/apps/${appKey}/permission-template-imports/${previewId}/confirm`, {
        method: "POST",
      });
    },
    onSuccess: async (payload) => {
      const version = String(payload.catalog_version ?? payload.template_version ?? "");
      toast.success("导入成功", `当前目录版本：${version}`);
      await queryClient.invalidateQueries({ queryKey: versionsQueryPrefix });
    },
    onError: (error: Error) => {
      toast.error("Manifest 导入失败", error.message);
    },
  });
  const updateContent = (nextContent: string) => {
    contentRef.current = nextContent;
    contentGenerationRef.current += 1;
    previewRequestRef.current += 1;
    setContent(nextContent);
    setPreview(null);
  };
  const currentPreview =
    preview &&
    preview.generation === contentGenerationRef.current &&
    preview.contentFingerprint === manifestContentFingerprint(content)
      ? preview
      : null;

  return (
    <section className="space-y-6">
      <CurrentManifestPanel
        appKey={appKey}
        onSaved={async () => {
          await queryClient.invalidateQueries({ queryKey: versionsQueryPrefix });
        }}
      />
      <PanelSurface className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.yaml,.yml,application/json,text/yaml,text/plain"
          className="sr-only"
          aria-label="上传 Manifest 文件"
          disabled={importMutation.isPending}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (!file) {
              return;
            }
            const fileReadId = ++fileReadRef.current;
            previewRequestRef.current += 1;
            contentGenerationRef.current += 1;
            setPreview(null);
            void file.text().then((fileContent) => {
              if (fileReadId === fileReadRef.current) {
                updateContent(fileContent);
              }
            });
          }}
        />
        <Button icon={<FileUp size={16} />} disabled={importMutation.isPending} onClick={() => fileInputRef.current?.click()}>
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
          disabled={importMutation.isPending}
          onChange={(event) => {
            fileReadRef.current += 1;
            updateContent(event.currentTarget.value);
          }}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          icon={<Eye size={16} />}
          disabled={!content || previewMutation.isPending}
          onClick={() => {
            const requestId = ++previewRequestRef.current;
            const contentSnapshot = contentRef.current;
            previewMutation.mutate({
              contentSnapshot,
              contentFingerprint: manifestContentFingerprint(contentSnapshot),
              generation: contentGenerationRef.current,
              requestId,
            });
          }}
        >
          预览差异
        </Button>
        <Button
          variant="primary"
          icon={<UploadCloud size={16} />}
          disabled={!currentPreview?.payload.preview_id || importMutation.isPending}
          onClick={() => {
            const previewId = currentPreview?.payload.preview_id;
            if (!previewId || !currentPreview) {
              return;
            }
            importMutation.mutate({
              previewId,
              contentFingerprint: currentPreview.contentFingerprint,
              generation: currentPreview.generation,
            });
          }}
        >
          确认导入
        </Button>
      </div>
      {versionsQuery.error ? <StatusBanner tone="signal" title="版本历史加载失败" message={(versionsQuery.error as Error).message} /> : null}
      {currentPreview ? <ManifestDiffView preview={currentPreview.payload} /> : null}
      <div className="space-y-3">
        <h2 className="text-base font-semibold text-ink">版本历史</h2>
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
            {versionsQuery.isLoading ? (
              <TableSkeletonRows columns={versionColumns.length} />
            ) : versionsTable.getRowModel().rows.length > 0 ? (
              versionsTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={versionColumns.length}>
                <EmptyState title="暂无版本历史" description="确认导入清单后会在这里记录版本。" />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
          <TablePagination table={versionsTable} totalItems={versionsQuery.data?.pagination?.total_items ?? 0} />
        </TableFrame>
      </div>
    </section>
  );
}

function CurrentManifestPanel({ appKey, onSaved }: { appKey: string; onSaved: () => Promise<void> }) {
  const { t } = useI18n();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [jsonError, setJsonError] = useState("");
  const manifestQuery = useQuery({
    queryKey: ["console", "app", appKey, "manifest"],
    queryFn: () => apiRequest<JsonObject>(`/console/api/v1/apps/${appKey}/manifest`),
  });
  const manifestText = manifestQuery.data ? JSON.stringify(manifestQuery.data, null, 2) : "";
  const saveMutation = useMutation({
    mutationFn: async ({ draftSnapshot, draftFingerprint }: { draftSnapshot: string; draftFingerprint: string }) => {
      const preview = await apiRequest<ManifestPreviewPayload>(
        `/console/api/v1/apps/${appKey}/permission-template-imports/preview`,
        { method: "POST", body: { template_format: "json", template: draftSnapshot } },
      );
      if (!preview.preview_id) {
        throw new Error(t("manifest.current.saveFailedNoPreview"));
      }
      if (draftFingerprint !== manifestContentFingerprint(draftRef.current)) {
        throw new Error("Manifest 内容已变化，请重新保存。");
      }
      return apiRequest<ManifestImportPayload>(
        `/console/api/v1/apps/${appKey}/permission-template-imports/${preview.preview_id}/confirm`,
        { method: "POST" },
      );
    },
    onSuccess: async (payload) => {
      const version = String(payload.catalog_version ?? payload.template_version ?? "");
      toast.success(t("manifest.current.saveSuccess"), `catalog_version: ${version}`);
      setEditing(false);
      await manifestQuery.refetch();
      await onSaved();
    },
    onError: (error: Error) => {
      toast.error(t("manifest.current.saveFailed"), error.message);
    },
  });

  const startEdit = () => {
    if (!manifestQuery.data) {
      return;
    }
    const currentVersion = Number(manifestQuery.data.schema_version ?? 0);
    // 导入管线要求 schema_version 严格递增, 进入编辑时预先自动 +1。
    const draftManifest = { ...manifestQuery.data, schema_version: currentVersion + 1 };
    const nextDraft = JSON.stringify(draftManifest, null, 2);
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    setJsonError("");
    setEditing(true);
  };

  const save = () => {
    try {
      JSON.parse(draft);
    } catch {
      setJsonError(t("manifest.current.invalidJson"));
      return;
    }
    setJsonError("");
    saveMutation.mutate({ draftSnapshot: draft, draftFingerprint: manifestContentFingerprint(draft) });
  };

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-ink">{t("manifest.current.title")}</h2>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("manifest.current.description")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            icon={<RefreshCcw size={15} />}
            loading={manifestQuery.isFetching}
            onClick={() => void manifestQuery.refetch()}
          >
            {t("manifest.current.refresh")}
          </Button>
          {editing ? (
            <>
              <Button icon={<X size={15} />} disabled={saveMutation.isPending} onClick={() => setEditing(false)}>
                {t("manifest.current.cancel")}
              </Button>
              <Button
                variant="primary"
                icon={<Save size={15} />}
                loading={saveMutation.isPending}
                disabled={saveMutation.isPending}
                onClick={save}
              >
                {t("manifest.current.save")}
              </Button>
            </>
          ) : (
            <Button icon={<Pencil size={15} />} disabled={!manifestQuery.data} onClick={startEdit}>
              {t("manifest.current.edit")}
            </Button>
          )}
        </div>
      </div>
      {manifestQuery.error ? (
        <StatusBanner tone="signal" title={t("manifest.current.loadFailed")} message={(manifestQuery.error as Error).message} />
      ) : null}
      {jsonError ? <StatusBanner tone="signal" title={jsonError} /> : null}
      {editing ? (
        <>
          <TextArea
            aria-label={t("manifest.current.title")}
            rows={18}
            className="font-mono text-xs leading-5"
            value={draft}
            disabled={saveMutation.isPending}
            onChange={(event) => {
              draftRef.current = event.currentTarget.value;
              setDraft(event.currentTarget.value);
            }}
          />
          <p className="text-body text-ink-soft">{t("manifest.current.saveHint")}</p>
        </>
      ) : manifestQuery.data ? (
        <div className="max-h-96 overflow-y-auto">
          <CodeBlock language="json" code={manifestText} />
        </div>
      ) : null}
    </PanelSurface>
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
      <TablePagination table={table} totalItems={items.length} />
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

function manifestContentFingerprint(content: string): string {
  // 保留规范化后的完整内容作为同步身份，避免非加密短哈希碰撞后确认错误预览。
  return content.replace(/\r\n?/g, "\n").trim();
}
