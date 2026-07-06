import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCcw } from "lucide-react";
import { Fragment, useState, type FormEvent } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TableActionCell, TableRowActionButton } from "../../components/ui/TableActions";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput } from "../../components/UserSelect";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject, ListPayload } from "../../lib/api";
import type { ApprovalTemplateItem, ApprovalTemplateTestResult } from "../../lib/domain";
import { formatDateTime } from "../../lib/status";

const TEMPLATES_QUERY_KEY = ["console", "approval-templates"];

interface TemplateFormPayload {
  app_key: string;
  key: string;
  name: string;
  dingtalk_process_code: string;
  form_mapping: JsonObject;
  is_active: boolean;
}

export function ApprovalTemplatesPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [editorState, setEditorState] = useState<{ template: ApprovalTemplateItem | null } | null>(null);
  const [testTemplate, setTestTemplate] = useState<ApprovalTemplateItem | null>(null);
  const templatesQuery = useQuery({
    queryKey: TEMPLATES_QUERY_KEY,
    queryFn: () => apiRequest<ListPayload<ApprovalTemplateItem>>("/console/api/v1/approval-templates"),
  });
  const templates = itemsFromPayload<ApprovalTemplateItem>(templatesQuery.data);
  const saveMutation = useMutation({
    mutationFn: ({ template, payload }: { template: ApprovalTemplateItem | null; payload: TemplateFormPayload }) => {
      if (template) {
        // PATCH 契约不接受 app_key/key(作用域与标识创建后不可改), 只提交可变字段。
        return apiRequest(`/console/api/v1/approval-templates/${template.id}`, {
          method: "PATCH",
          body: {
            name: payload.name,
            dingtalk_process_code: payload.dingtalk_process_code,
            form_mapping: payload.form_mapping,
            is_active: payload.is_active,
          } satisfies JsonObject,
        });
      }
      return apiRequest("/console/api/v1/approval-templates", {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY });
      setEditorState(null);
    },
  });

  const openEditor = (template: ApprovalTemplateItem | null) => {
    saveMutation.reset();
    setEditorState({ template });
  };

  const columns: ColumnDef<ApprovalTemplateItem>[] = [
    {
      header: t("approvalTemplates.column.key"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{row.original.key}</code>,
    },
    {
      header: t("common.name"),
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      header: t("approvalTemplates.column.app"),
      cell: ({ row }) =>
        row.original.app_key ? (
          <code className={MONO_TEXT_CLASS}>{row.original.app_key}</code>
        ) : (
          <Badge tone="bond">{t("approvalTemplates.platformShared")}</Badge>
        ),
    },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>
          {row.original.is_active ? t("common.enabled") : t("common.disabled")}
        </Badge>
      ),
    },
    {
      header: t("common.updatedAt"),
      cell: ({ row }) => formatDateTime(row.original.updated_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => openEditor(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
          <TableRowActionButton type="button" onClick={() => setTestTemplate(row.original)}>
            {t("approvalTemplates.test.action")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const table = useReactTable({
    data: templates,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.approvalCenter")}
        title={t("nav.console.approvalTemplates")}
        description={t("approvalTemplates.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => openEditor(null)}>
              {t("approvalTemplates.create")}
            </Button>
          </>
        }
      />
      {templatesQuery.error && templates.length > 0 ? (
        <StatusBanner tone="signal" title={t("approvalTemplates.loadFailed")} message={(templatesQuery.error as Error).message} />
      ) : null}
      {templatesQuery.error && templates.length === 0 ? (
        <PageState
          tone="signal"
          title={t("approvalTemplates.loadFailed")}
          description={(templatesQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <TableFrame>
          <TableRoot>
            <TableHead>
              {table.getHeaderGroups().map((headerGroup) => (
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
              {templatesQuery.isLoading ? (
                <TableSkeletonRows columns={table.getAllLeafColumns().length} />
              ) : table.getRowModel().rows.length > 0 ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) =>
                      cell.column.id === "actions" ? (
                        <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                      ) : (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ),
                    )}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
                  <EmptyState title={t("approvalTemplates.empty.title")} description={t("approvalTemplates.empty.description")} />
                </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
        </TableFrame>
      )}
      {editorState ? (
        <TemplateEditorDialog
          template={editorState.template}
          errorMessage={saveMutation.error ? (saveMutation.error as Error).message : ""}
          isSubmitting={saveMutation.isPending}
          onClose={() => setEditorState(null)}
          onSubmit={(payload) => saveMutation.mutate({ template: editorState.template, payload })}
        />
      ) : null}
      {testTemplate ? <TemplateTestDialog template={testTemplate} onClose={() => setTestTemplate(null)} /> : null}
    </>
  );
}

/** 校验文本为 JSON 对象(空文本视为 {}); 失败返回 null。 */
function parseJsonObject(text: string): JsonObject | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return {};
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as JsonObject;
    }
  } catch {
    return null;
  }
  return null;
}

function formatJsonObject(value: JsonObject | undefined): string {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

function TemplateEditorDialog({
  template,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  template: ApprovalTemplateItem | null;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TemplateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [appKey, setAppKey] = useState(template?.app_key ?? "");
  const [key, setKey] = useState(template?.key ?? "");
  const [name, setName] = useState(template?.name ?? "");
  const [processCode, setProcessCode] = useState(template?.dingtalk_process_code ?? "");
  const [formMappingText, setFormMappingText] = useState(formatJsonObject(template?.form_mapping));
  const [isActive, setIsActive] = useState(template?.is_active ?? true);
  const [mappingError, setMappingError] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formMapping = parseJsonObject(formMappingText);
    if (formMapping === null) {
      setMappingError(t("approvalTemplates.invalidJson"));
      return;
    }
    setMappingError("");
    onSubmit({
      app_key: appKey.trim(),
      key: key.trim(),
      name: name.trim(),
      dingtalk_process_code: processCode.trim(),
      form_mapping: formMapping,
      is_active: isActive,
    });
  };

  return (
    <Dialog
      title={template ? t("approvalTemplates.editTitle") : t("approvalTemplates.createTitle")}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="approval-template-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="approval-template-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("approvalTemplates.field.appKey")} hint={t("approvalTemplates.field.appKeyHint")}>
          <TextInput
            value={appKey}
            disabled={Boolean(template)}
            autoComplete="off"
            onChange={(event) => setAppKey(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("approvalTemplates.field.key")} hint={t("approvalTemplates.field.keyHint")}>
          <TextInput
            value={key}
            disabled={Boolean(template)}
            required={!template}
            autoComplete="off"
            onChange={(event) => setKey(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("common.name")}>
          <TextInput value={name} required onChange={(event) => setName(event.currentTarget.value)} />
        </Field>
        <Field label={t("approvalTemplates.field.processCode")}>
          <TextInput
            value={processCode}
            required
            autoComplete="off"
            onChange={(event) => setProcessCode(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("approvalTemplates.field.formMapping")} hint={t("approvalTemplates.field.formMappingHint")} error={mappingError}>
          <TextArea
            rows={8}
            spellCheck={false}
            className="font-mono text-caption"
            value={formMappingText}
            onChange={(event) => {
              setFormMappingText(event.currentTarget.value);
              if (mappingError) {
                setMappingError("");
              }
            }}
          />
        </Field>
        <label className="inline-flex items-center gap-2 text-body text-ink">
          <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.currentTarget.checked)} />
          <span>{t("approvalTemplates.field.isActive")}</span>
        </label>
        {errorMessage ? <StatusBanner tone="signal" title={t("approvalTemplates.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

function TemplateTestDialog({ template, onClose }: { template: ApprovalTemplateItem; onClose: () => void }) {
  const { t } = useI18n();
  const [originatorUserId, setOriginatorUserId] = useState("");
  const [appKey, setAppKey] = useState("");
  const [formText, setFormText] = useState("");
  const [originatorError, setOriginatorError] = useState("");
  const [appKeyError, setAppKeyError] = useState("");
  const [formError, setFormError] = useState("");
  const isPlatformTemplate = template.app_key === "";
  const testMutation = useMutation({
    mutationFn: (body: JsonObject) =>
      apiRequest<ApprovalTemplateTestResult>(`/console/api/v1/approval-templates/${template.id}/test`, {
        method: "POST",
        body,
      }),
  });
  const result = testMutation.data;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    let hasError = false;
    if (originatorUserId.trim() === "") {
      setOriginatorError(t("approvalTemplates.test.originatorRequired"));
      hasError = true;
    }
    if (isPlatformTemplate && appKey.trim() === "") {
      setAppKeyError(t("approvalTemplates.test.appKeyRequired"));
      hasError = true;
    }
    const form = parseJsonObject(formText);
    if (form === null) {
      setFormError(t("approvalTemplates.invalidJson"));
      hasError = true;
    }
    if (hasError || form === null) {
      return;
    }
    testMutation.mutate({
      originator_user_id: originatorUserId.trim(),
      ...(isPlatformTemplate ? { app_key: appKey.trim() } : {}),
      ...(Object.keys(form).length > 0 ? { form } : {}),
    });
  };

  return (
    <Dialog
      title={t("approvalTemplates.test.action")}
      eyebrow={<code>{template.key}</code>}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.close")}
          </Button>
          <Button
            form="approval-template-test-form"
            type="submit"
            variant="primary"
            loading={testMutation.isPending}
            disabled={testMutation.isPending}
          >
            {t("approvalTemplates.test.submit")}
          </Button>
        </>
      }
    >
      <form id="approval-template-test-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{t("approvalTemplates.test.description")}</p>
        <Field label={t("approvalTemplates.test.originator")} error={originatorError} as="group">
          <UserSearchInput
            value={originatorUserId}
            aria-label={t("approvalTemplates.test.originator")}
            onChange={(next) => {
              setOriginatorUserId(next);
              if (originatorError && next.trim() !== "") {
                setOriginatorError("");
              }
            }}
          />
        </Field>
        {isPlatformTemplate ? (
          <Field label={t("approvalTemplates.test.appKey")} hint={t("approvalTemplates.test.appKeyHint")} error={appKeyError}>
            <TextInput
              value={appKey}
              autoComplete="off"
              onChange={(event) => {
                setAppKey(event.currentTarget.value);
                if (appKeyError && event.currentTarget.value.trim() !== "") {
                  setAppKeyError("");
                }
              }}
            />
          </Field>
        ) : null}
        <Field label={t("approvalTemplates.test.form")} error={formError}>
          <TextArea
            rows={5}
            spellCheck={false}
            className="font-mono text-caption"
            value={formText}
            onChange={(event) => {
              setFormText(event.currentTarget.value);
              if (formError) {
                setFormError("");
              }
            }}
          />
        </Field>
        {testMutation.error ? (
          <StatusBanner tone="signal" title={t("approvalTemplates.test.failed")} message={(testMutation.error as Error).message} />
        ) : null}
        {result ? (
          <div role="status" className="space-y-3">
            <StatusBanner tone="evergreen" title={t("approvalTemplates.test.success")} />
            <dl className="grid gap-2 rounded-[3px] border border-ink/10 bg-paper-soft p-4 text-body text-ink-soft">
              <div className="flex items-center justify-between gap-4">
                <dt>{t("approvalTemplates.test.instanceId")}</dt>
                <dd className="font-mono text-ink">{result.instance_id}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt>{t("approvalTemplates.test.dingtalkInstanceId")}</dt>
                <dd className="font-mono text-ink">{result.dingtalk_process_instance_id || "-"}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt>{t("common.status")}</dt>
                <dd className="font-mono text-ink">{result.status}</dd>
              </div>
            </dl>
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}
