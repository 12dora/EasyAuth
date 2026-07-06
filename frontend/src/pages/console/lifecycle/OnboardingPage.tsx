import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCcw, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserSearchInput } from "../../../components/UserSelect";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
import { TableActionCell, TableRowActionButton } from "../../../components/ui/TableActions";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
  TableSkeletonRows,
} from "../../../components/ui/TablePrimitives";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type {
  AppListPayload,
  AppSummary,
  AuthorizationGroupItem,
  OnboardResult,
  OnboardingTemplateItemRow,
  OnboardingTemplateRow,
  PermissionItem,
} from "../../../lib/domain";
import { formatDateTime, grantTypeLabel } from "../../../lib/status";
import type { Translator } from "../../../lib/status";

const TEMPLATES_QUERY_KEY = ["console", "onboarding-templates"];

type TemplateItemKind = "group" | "permission";

interface TemplateItemDraft {
  app_key: string;
  kind: TemplateItemKind;
  key: string;
  name: string;
  scope_key: string;
  grant_type: string;
  duration_days: number | null;
}

interface TemplateFormPayload {
  name: string;
  description: string;
  is_active: boolean;
  items: TemplateItemDraft[];
}

export function OnboardingPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [editorState, setEditorState] = useState<{ template: OnboardingTemplateRow | null } | null>(null);
  const [onboardOpen, setOnboardOpen] = useState(false);

  const templatesQuery = useQuery({
    queryKey: TEMPLATES_QUERY_KEY,
    queryFn: () => apiRequest<ListPayload<OnboardingTemplateRow>>("/console/api/v1/lifecycle/onboarding-templates"),
  });
  const templates = itemsFromPayload<OnboardingTemplateRow>(templatesQuery.data);

  const saveMutation = useMutation({
    mutationFn: ({ template, payload }: { template: OnboardingTemplateRow | null; payload: TemplateFormPayload }) => {
      const body = {
        name: payload.name,
        description: payload.description,
        is_active: payload.is_active,
        items: payload.items.map((item) => ({
          app_key: item.app_key,
          ...(item.kind === "group" ? { authorization_group_key: item.key } : { permission_key: item.key }),
          ...(item.scope_key ? { scope_key: item.scope_key } : {}),
          grant_type: item.grant_type,
          ...(item.grant_type === "timed" && item.duration_days ? { duration_days: item.duration_days } : {}),
        })),
      } satisfies JsonObject;
      if (template) {
        return apiRequest(`/console/api/v1/lifecycle/onboarding-templates/${template.id}`, { method: "PATCH", body });
      }
      return apiRequest("/console/api/v1/lifecycle/onboarding-templates", { method: "POST", body });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY });
      setEditorState(null);
    },
  });

  const openEditor = (template: OnboardingTemplateRow | null) => {
    saveMutation.reset();
    setEditorState({ template });
  };

  const columns = templateColumns(t, openEditor);
  const table = useReactTable({
    data: templates,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("nav.console.onboarding")}
        description={t("onboarding.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" icon={<Plus size={16} />} onClick={() => openEditor(null)}>
              {t("onboarding.templates.create")}
            </Button>
            <Button type="button" variant="primary" icon={<UserPlus size={16} />} onClick={() => setOnboardOpen(true)}>
              {t("onboarding.onboard.action")}
            </Button>
          </>
        }
      />
      {templatesQuery.error && templates.length > 0 ? (
        <StatusBanner tone="signal" title={t("onboarding.templates.loadFailed")} message={(templatesQuery.error as Error).message} />
      ) : null}
      {templatesQuery.error && templates.length === 0 ? (
        <PageState
          tone="signal"
          title={t("onboarding.templates.loadFailed")}
          description={(templatesQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-ink">{t("onboarding.templates.title")}</h2>
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
                          <TableActionCell key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableActionCell>
                        ) : (
                          <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                        ),
                      )}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
                    <EmptyState title={t("onboarding.templates.empty.title")} description={t("onboarding.templates.empty.description")} />
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
          </TableFrame>
        </section>
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
      {onboardOpen ? <OnboardDialog templates={templates.filter((template) => template.is_active)} onClose={() => setOnboardOpen(false)} /> : null}
    </>
  );
}

function templateColumns(t: Translator, onEdit: (template: OnboardingTemplateRow) => void): ColumnDef<OnboardingTemplateRow>[] {
  return [
    {
      header: t("common.name"),
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      header: t("common.description"),
      cell: ({ row }) => row.original.description || "-",
    },
    {
      header: t("onboarding.templates.column.items"),
      cell: ({ row }) => t("onboarding.templates.itemCount", { count: row.original.items.length }),
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
        <TableRowActionButton type="button" onClick={() => onEdit(row.original)}>
          {t("common.edit")}
        </TableRowActionButton>
      ),
    },
  ];
}

function templateItemLine(t: Translator, item: { name: string; key: string; scope_key: string; grant_type: string; duration_days: number | null; kind: string }): string {
  const kindLabel = item.kind === "group" ? t("onboarding.editor.kind.group") : t("onboarding.editor.kind.permission");
  const term =
    item.grant_type === "timed" && item.duration_days
      ? t("onboarding.item.timedDays", { days: item.duration_days })
      : grantTypeLabel(t, item.grant_type);
  const scope = item.scope_key ? ` · ${item.scope_key}` : "";
  return `${kindLabel} · ${item.name || item.key}${scope} · ${term}`;
}

function TemplateEditorDialog({
  template,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  template: OnboardingTemplateRow | null;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TemplateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(template?.name ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [isActive, setIsActive] = useState(template?.is_active ?? true);
  const [items, setItems] = useState<TemplateItemDraft[]>(() =>
    (template?.items ?? []).map((item: OnboardingTemplateItemRow) => ({
      app_key: item.app_key,
      kind: item.kind === "group" ? "group" : "permission",
      key: item.key,
      name: item.name,
      scope_key: item.scope_key,
      grant_type: item.grant_type,
      duration_days: item.duration_days,
    })),
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      return;
    }
    onSubmit({ name: normalizedName, description: description.trim(), is_active: isActive, items });
  };

  return (
    <Dialog
      title={template ? t("onboarding.editor.editTitle") : t("onboarding.editor.createTitle")}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="onboarding-template-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="onboarding-template-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} required onChange={(event) => setName(event.currentTarget.value)} />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={2} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <label className="inline-flex items-center gap-2 text-body text-ink">
          <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.currentTarget.checked)} />
          <span>{t("onboarding.editor.isActive")}</span>
        </label>
        <Field label={t("onboarding.editor.items")} as="group">
          <div className="space-y-2">
            {items.length === 0 ? (
              <p className="text-caption text-ink-faint">{t("onboarding.editor.itemsEmpty")}</p>
            ) : (
              <ul className="grid gap-1.5">
                {items.map((item, index) => (
                  <li
                    key={`${item.app_key}-${item.kind}-${item.key}-${item.scope_key}-${index}`}
                    className="flex items-center justify-between gap-3 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2"
                  >
                    <span className="min-w-0 text-body text-ink">
                      <code className="mr-2 text-caption text-ink-faint">{item.app_key}</code>
                      {templateItemLine(t, item)}
                    </span>
                    <Button
                      size="sm"
                      type="button"
                      variant="ghost-danger"
                      onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    >
                      {t("onboarding.editor.removeItem")}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <TemplateItemComposer onAdd={(item) => setItems((current) => [...current, item])} />
          </div>
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("onboarding.editor.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

/** 模板项编辑器: 选应用 → 选授权组或权限(+范围) → 期限, 逐项添加。 */
function TemplateItemComposer({ onAdd }: { onAdd: (item: TemplateItemDraft) => void }) {
  const { t } = useI18n();
  const [appKey, setAppKey] = useState("");
  const [kind, setKind] = useState<TemplateItemKind>("group");
  const [targetKey, setTargetKey] = useState("");
  const [scopeKey, setScopeKey] = useState("");
  const [grantType, setGrantType] = useState("permanent");
  const [durationDays, setDurationDays] = useState("30");

  const appsQuery = useQuery({
    queryKey: ["console", "apps", "selector"],
    queryFn: () => apiRequest<AppListPayload>("/console/api/v1/apps?page=1&page_size=100"),
  });
  const apps = itemsFromPayload<AppSummary>(appsQuery.data);

  const groupsQuery = useQuery({
    queryKey: ["console", "app", appKey, "authorization-groups"],
    queryFn: () => apiRequest<ListPayload<AuthorizationGroupItem>>(`/console/api/v1/apps/${appKey}/authorization-groups`),
    enabled: Boolean(appKey) && kind === "group",
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<ListPayload<PermissionItem>>(`/console/api/v1/apps/${appKey}/permissions`),
    enabled: Boolean(appKey) && kind === "permission",
  });
  const groups = itemsFromPayload<AuthorizationGroupItem>(groupsQuery.data);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);
  const selectedPermission = permissions.find((permission) => permission.key === targetKey);
  const scopeOptions = kind === "permission" ? (selectedPermission?.supported_scopes ?? []) : [];
  const optionsError = (groupsQuery.error ?? permissionsQuery.error ?? appsQuery.error) as Error | null;

  const targetName =
    kind === "group"
      ? groups.find((group) => group.key === targetKey)?.name ?? ""
      : selectedPermission?.name ?? "";

  const add = () => {
    if (!appKey || !targetKey) {
      return;
    }
    onAdd({
      app_key: appKey,
      kind,
      key: targetKey,
      name: targetName,
      scope_key: scopeKey,
      grant_type: grantType,
      duration_days: grantType === "timed" ? Math.max(1, Number(durationDays) || 1) : null,
    });
    setTargetKey("");
    setScopeKey("");
  };

  return (
    <div className="space-y-3 rounded-[3px] border border-dashed border-ink/20 p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("onboarding.editor.app")}>
          <SelectInput
            value={appKey}
            onChange={(event) => {
              setAppKey(event.currentTarget.value);
              setTargetKey("");
              setScopeKey("");
            }}
          >
            <option value="">{t("onboarding.editor.appPlaceholder")}</option>
            {apps.map((app) => (
              <option key={app.app_key} value={app.app_key}>
                {app.name} ({app.app_key})
              </option>
            ))}
          </SelectInput>
        </Field>
        <Field label={t("onboarding.editor.kind")}>
          <SelectInput
            value={kind}
            onChange={(event) => {
              setKind(event.currentTarget.value as TemplateItemKind);
              setTargetKey("");
              setScopeKey("");
            }}
          >
            <option value="group">{t("onboarding.editor.kind.group")}</option>
            <option value="permission">{t("onboarding.editor.kind.permission")}</option>
          </SelectInput>
        </Field>
        <Field label={t("onboarding.editor.target")}>
          <SelectInput
            value={targetKey}
            disabled={!appKey}
            onChange={(event) => {
              setTargetKey(event.currentTarget.value);
              setScopeKey("");
            }}
          >
            <option value="">{t("onboarding.editor.targetPlaceholder")}</option>
            {kind === "group"
              ? groups.map((group) => (
                  <option key={group.key} value={group.key}>
                    {group.name} ({group.key})
                  </option>
                ))
              : permissions.map((permission) => (
                  <option key={permission.key} value={permission.key}>
                    {permission.name} ({permission.key})
                  </option>
                ))}
          </SelectInput>
        </Field>
        {kind === "permission" ? (
          <Field label={t("onboarding.editor.scope")}>
            <SelectInput value={scopeKey} disabled={!targetKey} onChange={(event) => setScopeKey(event.currentTarget.value)}>
              <option value="">{t("onboarding.editor.scopeDefault")}</option>
              {scopeOptions.map((scope) => (
                <option key={scope} value={scope}>
                  {scope}
                </option>
              ))}
            </SelectInput>
          </Field>
        ) : null}
        <Field label={t("onboarding.editor.grantType")}>
          <SelectInput value={grantType} onChange={(event) => setGrantType(event.currentTarget.value)}>
            <option value="permanent">{t("status.grantType.permanent")}</option>
            <option value="timed">{t("status.grantType.timed")}</option>
          </SelectInput>
        </Field>
        {grantType === "timed" ? (
          <Field label={t("onboarding.editor.durationDays")}>
            <TextInput
              type="number"
              min={1}
              max={3650}
              value={durationDays}
              onChange={(event) => setDurationDays(event.currentTarget.value)}
            />
          </Field>
        ) : null}
      </div>
      {optionsError ? (
        <StatusBanner tone="signal" title={t("onboarding.editor.optionsLoadFailed")} message={optionsError.message} />
      ) : null}
      <Button type="button" icon={<Plus size={15} />} disabled={!appKey || !targetKey} onClick={add}>
        {t("onboarding.editor.addItem")}
      </Button>
    </div>
  );
}

function OnboardDialog({ templates, onClose }: { templates: OnboardingTemplateRow[]; onClose: () => void }) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const selectedTemplate = templates.find((template) => String(template.id) === templateId);

  const onboardMutation = useMutation({
    mutationFn: () =>
      apiRequest<OnboardResult>("/console/api/v1/lifecycle/onboard", {
        method: "POST",
        body: { user_id: userId.trim(), template_id: Number(templateId) } satisfies JsonObject,
      }),
  });
  const result = onboardMutation.data;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!userId.trim() || !templateId) {
      return;
    }
    onboardMutation.mutate();
  };

  return (
    <Dialog
      title={t("onboarding.onboard.action")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.close")}
          </Button>
          <Button
            form="onboard-form"
            type="submit"
            variant="primary"
            loading={onboardMutation.isPending}
            disabled={onboardMutation.isPending || !userId.trim() || !templateId}
          >
            {t("onboarding.onboard.confirm")}
          </Button>
        </>
      }
    >
      <form id="onboard-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{t("onboarding.onboard.description")}</p>
        <Field label={t("onboarding.onboard.user")} as="group">
          <UserSearchInput value={userId} aria-label={t("onboarding.onboard.user")} onChange={setUserId} />
        </Field>
        <Field label={t("onboarding.onboard.template")}>
          <SelectInput value={templateId} onChange={(event) => setTemplateId(event.currentTarget.value)}>
            <option value="">{t("handover.transfer.templatePlaceholder")}</option>
            {templates.map((template) => (
              <option key={template.id} value={String(template.id)}>
                {template.name}
              </option>
            ))}
          </SelectInput>
        </Field>
        {selectedTemplate ? (
          <div className="space-y-2 rounded-[3px] border border-ink/10 bg-paper-soft p-3">
            <h3 className="text-caption font-semibold uppercase tracking-caps-wide text-ink-soft">
              {t("onboarding.onboard.previewTitle")}
            </h3>
            {selectedTemplate.items.length === 0 ? (
              <p className="text-caption text-ink-faint">{t("onboarding.onboard.previewEmpty")}</p>
            ) : (
              <ul className="grid gap-1 text-body text-ink">
                {selectedTemplate.items.map((item) => (
                  <li key={item.id}>
                    <code className="mr-2 text-caption text-ink-faint">{item.app_key}</code>
                    {templateItemLine(t, item)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
        {onboardMutation.error ? (
          <StatusBanner tone="signal" title={t("onboarding.onboard.failed")} message={(onboardMutation.error as Error).message} />
        ) : null}
        {result ? (
          <div role="status">
            <StatusBanner tone="evergreen" title={t("onboarding.onboard.success", { count: result.granted_app_count })} />
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}
