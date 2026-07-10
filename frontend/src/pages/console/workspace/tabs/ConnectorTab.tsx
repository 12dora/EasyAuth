import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlugZap, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { SchemaForm } from "../../../../components/SchemaForm";
import { StatusBanner } from "../../../../components/StatusBanner";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { PaginationBar } from "../../../../components/ui/PaginationBar";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
} from "../../../../components/ui/TablePrimitives";
import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject, ListPayload } from "../../../../lib/api";
import type {
  AuthorizationGroupItem,
  ConnectorExternalGroupItem,
  ConnectorInstanceItem,
  ConnectorInstancePayload,
  ConnectorMappingItem,
  ConnectorsPayload,
  ConnectorSyncRunItem,
  ConnectorTestResult,
  ConnectorTypeItem,
} from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { formatDateTime } from "../../../../lib/status";

interface MappingDraft {
  external_ref: string;
  auto_create: boolean;
}

interface ConnectorMappingsPayload extends ListPayload<ConnectorMappingItem> {
  revision: string;
}

interface TestCandidate {
  connectorKey: string;
  instanceId: number | null;
  config: JsonObject;
  fingerprint: string;
}

const RUN_STATUS_TONES: Record<
  string,
  "evergreen" | "amber" | "signal" | "neutral"
> = {
  success: "evergreen",
  partial: "amber",
  failed: "signal",
};

const RUN_TRIGGER_LABEL_KEYS: Record<string, MessageKey> = {
  periodic: "console.connector.trigger.periodic",
  event: "console.connector.trigger.event",
  manual: "console.connector.trigger.manual",
  offboard: "console.connector.trigger.offboard",
};

export function ConnectorTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const connectorsQueryKey = ["console", "app", appKey, "connectors"];

  const connectorsQuery = useQuery({
    queryKey: connectorsQueryKey,
    queryFn: () =>
      apiRequest<ConnectorsPayload>(
        `/console/api/v1/apps/${appKey}/connectors`,
      ),
    enabled: Boolean(appKey),
  });
  const connectorTypes = connectorsQuery.data?.connector_types ?? [];
  const instances = connectorsQuery.data?.data ?? [];

  const [selectedInstanceId, setSelectedInstanceId] = useState<number | null>(
    null,
  );
  const [selectedTypeKey, setSelectedTypeKey] = useState("");
  const [draftInstanceId, setDraftInstanceId] = useState<number | null>(null);
  const [configDraft, setConfigDraft] = useState<JsonObject>({});
  const [enabledDraft, setEnabledDraft] = useState(false);
  const [intervalDraft, setIntervalDraft] = useState("300");
  const [testedFingerprint, setTestedFingerprint] = useState<string | null>(
    null,
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const instance =
    instances.find((item) => item.id === selectedInstanceId) ?? null;
  const configuredTypeKeys = useMemo(
    () => new Set(instances.map((item) => item.connector_key)),
    [instances],
  );
  const availableTypes = connectorTypes.filter(
    (item) => !configuredTypeKeys.has(item.key),
  );

  const activeType: ConnectorTypeItem | null = useMemo(() => {
    const key = instance?.connector_key ?? selectedTypeKey;
    return connectorTypes.find((item) => item.key === key) ?? null;
  }, [connectorTypes, instance?.connector_key, selectedTypeKey]);

  useEffect(() => {
    if (!connectorsQuery.data || selectedTypeKey) {
      return;
    }
    if (
      selectedInstanceId !== null &&
      instances.some((item) => item.id === selectedInstanceId)
    ) {
      return;
    }
    setSelectedInstanceId(instances[0]?.id ?? null);
  }, [connectorsQuery.data, instances, selectedInstanceId, selectedTypeKey]);

  useEffect(() => {
    if (instance) {
      setConfigDraft(instance.config);
      setEnabledDraft(instance.enabled);
      setIntervalDraft(String(instance.reconcile_interval_seconds));
      setDraftInstanceId(instance.id);
      setTestedFingerprint(null);
    } else if (selectedTypeKey) {
      setConfigDraft({});
      setEnabledDraft(false);
      setIntervalDraft("300");
      setDraftInstanceId(null);
      setTestedFingerprint(null);
    }
  }, [instance, selectedTypeKey]);

  const connectorKey = instance?.connector_key ?? selectedTypeKey;
  const candidateFingerprint = connectorCandidateFingerprint(
    connectorKey,
    instance?.id ?? null,
    configDraft,
  );
  const currentCandidateFingerprint = useRef(candidateFingerprint);
  currentCandidateFingerprint.current = candidateFingerprint;

  const invalidateConnectors = () => {
    void queryClient.invalidateQueries({ queryKey: connectorsQueryKey });
  };

  const testMutation = useMutation({
    mutationFn: (candidate: TestCandidate) =>
      apiRequest<ConnectorTestResult>(
        `/console/api/v1/apps/${appKey}/connectors/test`,
        {
          method: "POST",
          body: {
            connector_key: candidate.connectorKey,
            config: candidate.config,
          } satisfies JsonObject,
        },
      ),
    onSuccess: (payload, candidate) => {
      if (candidate.fingerprint !== currentCandidateFingerprint.current) {
        return;
      }
      if (payload.ok) {
        setTestedFingerprint(candidate.fingerprint);
        toast.success(t("console.connector.testPassed"), payload.message);
        return;
      }
      setTestedFingerprint(null);
      toast.error(t("console.connector.testFailed"), payload.message);
    },
    onError: (error: Error, candidate) => {
      if (candidate.fingerprint !== currentCandidateFingerprint.current) {
        return;
      }
      setTestedFingerprint(null);
      toast.error(t("console.connector.testFailed"), error.message);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      const body = {
        enabled: enabledDraft,
        reconcile_interval_seconds: Number(intervalDraft) || 300,
        config: configDraft,
      } satisfies JsonObject;
      if (instance) {
        return apiRequest<ConnectorInstancePayload>(
          `/console/api/v1/apps/${appKey}/connectors/${instance.id}`,
          { method: "PUT", body },
        );
      }
      return apiRequest<ConnectorInstancePayload>(
        `/console/api/v1/apps/${appKey}/connectors`,
        {
          method: "POST",
          body: {
            ...body,
            connector_key: selectedTypeKey,
          } satisfies JsonObject,
        },
      );
    },
    onSuccess: (payload) => {
      queryClient.setQueryData<ConnectorsPayload>(
        connectorsQueryKey,
        (current) => {
          if (!current) {
            return current;
          }
          const next = current.data.filter(
            (item) => item.id !== payload.connector.id,
          );
          return { ...current, data: [...next, payload.connector] };
        },
      );
      setSelectedTypeKey("");
      setSelectedInstanceId(payload.connector.id);
      setDraftInstanceId(payload.connector.id);
      setTestedFingerprint(null);
      invalidateConnectors();
      toast.success(t("console.connector.saveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.saveFailed"), error.message);
    },
  });

  const reconcileMutation = useMutation({
    mutationFn: () =>
      apiRequest(
        `/console/api/v1/apps/${appKey}/connectors/${instance?.id}/reconcile`,
        {
          method: "POST",
          body: {} satisfies JsonObject,
        },
      ),
    onSuccess: () => {
      toast.success(t("console.connector.reconcileQueued"));
      void queryClient.invalidateQueries({
        queryKey: ["console", "app", appKey, "connector-sync-runs"],
      });
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.reconcileFailed"), error.message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/apps/${appKey}/connectors/${instance?.id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      const deletedInstanceId = instance?.id;
      queryClient.setQueryData<ConnectorsPayload>(
        connectorsQueryKey,
        (current) =>
          current && deletedInstanceId
            ? {
                ...current,
                data: current.data.filter(
                  (item) => item.id !== deletedInstanceId,
                ),
              }
            : current,
      );
      setDeleteConfirmOpen(false);
      setSelectedInstanceId(null);
      setSelectedTypeKey("");
      setDraftInstanceId(null);
      setConfigDraft({});
      setEnabledDraft(false);
      setTestedFingerprint(null);
      invalidateConnectors();
      toast.success(t("console.connector.deleteSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.deleteFailed"), error.message);
    },
  });

  const updateConfigDraft = (next: JsonObject) => {
    setConfigDraft(next);
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  const configChanged = Boolean(
    instance && stableJson(configDraft) !== stableJson(instance.config),
  );
  const testRequired =
    enabledDraft && (!instance || !instance.enabled || configChanged);
  const saveBlockedByTest =
    testRequired && testedFingerprint !== candidateFingerprint;
  const authoritativeConfigLoaded = connectorsQuery.isSuccess;
  const candidateLoaded = !instance || draftInstanceId === instance.id;
  const canOperate =
    authoritativeConfigLoaded &&
    candidateLoaded &&
    Boolean(connectorKey && activeType);
  const selectionValue = instance
    ? `instance:${instance.id}`
    : selectedTypeKey
      ? `new:${selectedTypeKey}`
      : "";

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="text-base font-semibold text-ink">
              {t("console.connector.heading")}
            </h2>
            <p className="max-w-3xl text-body leading-5 text-ink-soft">
              {t("console.connector.description")}
            </p>
          </div>
          {instance ? <InstanceStatusBadges t={t} instance={instance} /> : null}
        </div>
        {connectorsQuery.error ? (
          <StatusBanner
            tone="signal"
            title={t("console.connector.loadFailed")}
            message={(connectorsQuery.error as Error).message}
          />
        ) : null}
        {instance?.consecutive_failures ? (
          <StatusBanner
            tone={instance.consecutive_failures >= 3 ? "signal" : "amber"}
            title={t("console.connector.consecutiveFailures", {
              count: String(instance.consecutive_failures),
            })}
            message={instance.last_error}
          />
        ) : null}
        {!connectorsQuery.isLoading && !connectorsQuery.error && !instance ? (
          <StatusBanner
            tone="amber"
            title={t("console.connector.notConfigured")}
          />
        ) : null}
        {instance ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs leading-5 text-ink-faint">
              {t("console.connector.updatedMeta", {
                user: instance.updated_by || "-",
                time: formatDateTime(instance.updated_at),
              })}
            </span>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                icon={<RefreshCw size={14} />}
                loading={reconcileMutation.isPending}
                disabled={reconcileMutation.isPending || !instance.enabled}
                onClick={() => reconcileMutation.mutate()}
              >
                {t("console.connector.reconcileNow")}
              </Button>
              <Button
                type="button"
                variant="ghost-danger"
                icon={<Trash2 size={14} />}
                onClick={() => setDeleteConfirmOpen(true)}
              >
                {t("console.connector.deleteInstance")}
              </Button>
            </div>
          </div>
        ) : null}
        <form className="grid max-w-3xl gap-4" onSubmit={submit}>
          <Field label={t("console.connector.typeLabel")}>
            <SelectInput
              value={selectionValue}
              disabled={
                connectorsQuery.isLoading ||
                testMutation.isPending ||
                saveMutation.isPending
              }
              onChange={(event) => {
                const [kind, rawValue] = event.currentTarget.value.split(
                  ":",
                  2,
                );
                setDeleteConfirmOpen(false);
                setTestedFingerprint(null);
                if (kind === "instance") {
                  const nextInstance = instances.find(
                    (item) => item.id === Number(rawValue),
                  );
                  setSelectedTypeKey("");
                  setSelectedInstanceId(nextInstance?.id ?? null);
                  if (nextInstance) {
                    setConfigDraft(nextInstance.config);
                    setEnabledDraft(nextInstance.enabled);
                    setIntervalDraft(
                      String(nextInstance.reconcile_interval_seconds),
                    );
                    setDraftInstanceId(nextInstance.id);
                  }
                  return;
                }
                setSelectedInstanceId(null);
                setDraftInstanceId(null);
                setSelectedTypeKey(kind === "new" ? rawValue : "");
              }}
            >
              <option value="">{t("console.connector.typePlaceholder")}</option>
              {instances.map((item) => (
                <option
                  key={`instance:${item.id}`}
                  value={`instance:${item.id}`}
                >
                  {item.display_name}
                </option>
              ))}
              {availableTypes.map((item) => (
                <option key={`new:${item.key}`} value={`new:${item.key}`}>
                  {item.display_name}
                </option>
              ))}
            </SelectInput>
          </Field>
          {activeType ? (
            <>
              <SchemaForm
                schema={activeType.config_schema}
                value={configDraft}
                onChange={updateConfigDraft}
                configuredSecrets={instance?.configured_secrets ?? []}
                disabled={
                  !candidateLoaded ||
                  saveMutation.isPending ||
                  testMutation.isPending
                }
              />
              <Field
                label={t("console.connector.intervalLabel")}
                hint={t("console.connector.intervalHint")}
              >
                <TextInput
                  type="number"
                  min={60}
                  max={86400}
                  value={intervalDraft}
                  disabled={!candidateLoaded || saveMutation.isPending}
                  onChange={(event) =>
                    setIntervalDraft(event.currentTarget.value)
                  }
                />
              </Field>
              <label className="inline-flex items-center gap-2 text-body text-ink">
                <input
                  type="checkbox"
                  checked={enabledDraft}
                  disabled={!candidateLoaded || saveMutation.isPending}
                  onChange={(event) =>
                    setEnabledDraft(event.currentTarget.checked)
                  }
                />
                <span>{t("console.connector.enabled")}</span>
              </label>
              {saveBlockedByTest ? (
                <p className="text-xs leading-5 text-ink-soft">
                  {t("console.connector.testRequiredHint")}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  icon={<PlugZap size={15} />}
                  loading={testMutation.isPending}
                  disabled={testMutation.isPending || !canOperate}
                  onClick={() =>
                    testMutation.mutate({
                      connectorKey,
                      instanceId: instance?.id ?? null,
                      config: configDraft,
                      fingerprint: candidateFingerprint,
                    })
                  }
                >
                  {t("console.connector.test")}
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  icon={<Save size={15} />}
                  loading={saveMutation.isPending}
                  disabled={
                    saveMutation.isPending || !canOperate || saveBlockedByTest
                  }
                >
                  {t("common.save")}
                </Button>
              </div>
            </>
          ) : connectorTypes.length === 0 && !connectorsQuery.isLoading ? (
            <EmptyState title={t("console.connector.noTypes")} />
          ) : null}
        </form>
        <p className="text-xs leading-5 text-ink-faint">
          {t("console.connector.superuserHint")}
        </p>
      </PanelSurface>
      {instance ? (
        <MappingsPanel
          key={`mappings:${instance.id}`}
          appKey={appKey}
          instance={instance}
        />
      ) : null}
      {instance ? (
        <SyncRunsPanel
          key={`runs:${instance.id}`}
          appKey={appKey}
          instance={instance}
        />
      ) : null}
      {deleteConfirmOpen && instance ? (
        <Dialog
          title={t("console.connector.deleteTitle")}
          size="sm"
          onClose={() => setDeleteConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setDeleteConfirmOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                loading={deleteMutation.isPending}
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate()}
              >
                {t("console.connector.deleteConfirm")}
              </Button>
            </>
          }
        >
          <p className="text-body leading-6 text-ink">
            {t("console.connector.deleteMessage")}
          </p>
        </Dialog>
      ) : null}
    </section>
  );
}

function InstanceStatusBadges({
  t,
  instance,
}: {
  t: Translator;
  instance: ConnectorInstanceItem;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={instance.enabled ? "evergreen" : "neutral"}>
        {instance.enabled ? t("common.enabled") : t("common.disabled")}
      </Badge>
      <span className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">
        {t("console.connector.statusLabel")}
      </span>
      {instance.last_reconcile_at ? (
        <>
          <Badge tone={RUN_STATUS_TONES[instance.last_status] ?? "neutral"}>
            {runStatusLabel(t, instance.last_status)}
          </Badge>
          <span className="text-xs text-ink-faint">
            {formatDateTime(instance.last_reconcile_at)}
          </span>
        </>
      ) : (
        <Badge tone="neutral">{t("console.connector.status.never")}</Badge>
      )}
    </div>
  );
}

function MappingsPanel({
  appKey,
  instance,
}: {
  appKey: string;
  instance: ConnectorInstanceItem;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const mappingsQueryKey = [
    "console",
    "app",
    appKey,
    "connector-mappings",
    instance.id,
  ];
  const [drafts, setDrafts] = useState<Record<string, MappingDraft>>({});

  const groupsQuery = useQuery({
    queryKey: ["console", "app", appKey, "authorization-groups"],
    queryFn: () =>
      apiRequest<ListPayload<AuthorizationGroupItem>>(
        `/console/api/v1/apps/${appKey}/authorization-groups`,
      ),
    enabled: Boolean(appKey),
  });
  const mappingsQuery = useQuery({
    queryKey: mappingsQueryKey,
    queryFn: () =>
      apiRequest<ConnectorMappingsPayload>(
        `/console/api/v1/apps/${appKey}/connectors/${instance.id}/mappings`,
      ),
  });
  const externalGroupsQuery = useQuery({
    queryKey: [
      "console",
      "app",
      appKey,
      "connector-external-groups",
      instance.id,
    ],
    queryFn: () =>
      apiRequest<ListPayload<ConnectorExternalGroupItem>>(
        `/console/api/v1/apps/${appKey}/connectors/${instance.id}/external-groups`,
      ),
    retry: false,
  });

  const groups = (groupsQuery.data?.data ?? []).filter(
    (group) => group.is_active,
  );
  const externalGroups = externalGroupsQuery.data?.data ?? [];
  const datalistId = `connector-external-groups-${instance.id}`;

  useEffect(() => {
    if (!mappingsQuery.data) {
      return;
    }
    const mappings = mappingsQuery.data.data ?? [];
    setDrafts(
      Object.fromEntries(
        mappings.map((mapping) => [
          mapping.authorization_group_key,
          {
            external_ref: mapping.external_ref,
            auto_create: mapping.auto_create,
          },
        ]),
      ),
    );
  }, [mappingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<ConnectorMappingsPayload>(
        `/console/api/v1/apps/${appKey}/connectors/${instance.id}/mappings`,
        {
          method: "PUT",
          body: {
            revision: mappingsQuery.data?.revision ?? "",
            mappings: Object.entries(drafts)
              .filter(([, draft]) => draft.external_ref.trim() !== "")
              .map(([groupKey, draft]) => ({
                authorization_group_key: groupKey,
                external_ref: draft.external_ref.trim(),
                auto_create: draft.auto_create,
              })),
          } satisfies JsonObject,
        },
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(mappingsQueryKey, payload);
      toast.success(t("console.connector.mappingsSaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.connector.mappingsSaveFailed"), error.message);
    },
  });

  const setDraft = (groupKey: string, patch: Partial<MappingDraft>) => {
    setDrafts((current) => {
      const base = current[groupKey] ?? {
        external_ref: "",
        auto_create: false,
      };
      return { ...current, [groupKey]: { ...base, ...patch } };
    });
  };

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="text-base font-semibold text-ink">
            {t("console.connector.mappingsHeading")}
          </h3>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">
            {t("console.connector.mappingsDescription")}
          </p>
        </div>
        <Button
          type="button"
          variant="primary"
          icon={<Save size={15} />}
          loading={saveMutation.isPending}
          disabled={
            saveMutation.isPending ||
            !mappingsQuery.isSuccess ||
            !groupsQuery.isSuccess
          }
          onClick={() => saveMutation.mutate()}
        >
          {t("common.save")}
        </Button>
      </div>
      {externalGroupsQuery.error ? (
        <p className="text-xs leading-5 text-ink-soft">
          {t("console.connector.externalGroupsFailed")}
        </p>
      ) : null}
      {mappingsQuery.error || groupsQuery.error ? (
        <div className="space-y-2">
          <StatusBanner
            tone="signal"
            title={t("console.connector.loadFailed")}
            message={
              (mappingsQuery.error as Error | null)?.message ??
              (groupsQuery.error as Error).message
            }
          />
          <div>
            <Button
              type="button"
              onClick={() => {
                void mappingsQuery.refetch();
                void groupsQuery.refetch();
              }}
            >
              {t("common.retry")}
            </Button>
          </div>
        </div>
      ) : null}
      <datalist id={datalistId}>
        {externalGroups.map((group) => (
          <option key={group.ref} value={group.ref}>
            {group.name}
          </option>
        ))}
      </datalist>
      <TableFrame>
        <TableRoot>
          <TableHead>
            <TableRow>
              <TableHeaderCell>
                {t("console.connector.mappingsColumn.group")}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("console.connector.mappingsColumn.externalRef")}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("console.connector.mappingsColumn.autoCreate")}
              </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {groups.length === 0 ? (
              <TableEmptyRow colSpan={3}>
                <EmptyState title={t("console.connector.mappingsEmpty")} />
              </TableEmptyRow>
            ) : (
              groups.map((group) => {
                const draft = drafts[group.key] ?? {
                  external_ref: "",
                  auto_create: false,
                };
                return (
                  <TableRow key={group.key}>
                    <TableCell>
                      <span className="font-medium text-ink">{group.name}</span>{" "}
                      <code className="text-xs text-ink-faint">
                        {group.key}
                      </code>
                    </TableCell>
                    <TableCell>
                      <TextInput
                        list={datalistId}
                        className="max-w-72 font-mono"
                        aria-label={t(
                          "console.connector.mappingsColumn.externalRef",
                        )}
                        placeholder={t(
                          "console.connector.mappingsRefPlaceholder",
                        )}
                        value={draft.external_ref}
                        onChange={(event) =>
                          setDraft(group.key, {
                            external_ref: event.currentTarget.value,
                          })
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <label className="inline-flex items-center gap-2 text-body text-ink">
                        <input
                          type="checkbox"
                          checked={draft.auto_create}
                          disabled={draft.external_ref.trim() === ""}
                          onChange={(event) =>
                            setDraft(group.key, {
                              auto_create: event.currentTarget.checked,
                            })
                          }
                        />
                        <span>
                          {t("console.connector.mappingsAutoCreateLabel")}
                        </span>
                      </label>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </TableRoot>
      </TableFrame>
    </PanelSurface>
  );
}

function SyncRunsPanel({
  appKey,
  instance,
}: {
  appKey: string;
  instance: ConnectorInstanceItem;
}) {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const runsQuery = useQuery({
    queryKey: [
      "console",
      "app",
      appKey,
      "connector-sync-runs",
      instance.id,
      page,
      pageSize,
    ],
    queryFn: () =>
      apiRequest<ListPayload<ConnectorSyncRunItem>>(
        `/console/api/v1/apps/${appKey}/connectors/${instance.id}/sync-runs?page=${page}&page_size=${pageSize}`,
      ),
    refetchInterval: 30_000,
  });
  const runs = runsQuery.data?.data ?? [];
  const pagination = runsQuery.data?.pagination;
  const totalRows = pagination?.total_items ?? runs.length;
  const pageIndex = (pagination?.page ?? page) - 1;
  const effectivePageSize = pagination?.page_size ?? pageSize;
  const pageCount =
    pagination?.total_pages ??
    (totalRows === 0 ? 0 : Math.ceil(totalRows / effectivePageSize));
  const pageStart = totalRows === 0 ? 0 : pageIndex * effectivePageSize + 1;
  const pageEnd = totalRows === 0 ? 0 : pageStart + runs.length - 1;

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <h3 className="text-base font-semibold text-ink">
        {t("console.connector.runsHeading")}
      </h3>
      <TableFrame>
        <TableRoot>
          <TableHead>
            <TableRow>
              <TableHeaderCell>
                {t("console.connector.runsColumn.time")}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("console.connector.runsColumn.trigger")}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("console.connector.runsColumn.status")}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("console.connector.runsColumn.stats")}
              </TableHeaderCell>
              <TableHeaderCell>
                {t("console.connector.runsColumn.error")}
              </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {runs.length === 0 ? (
              <TableEmptyRow colSpan={5}>
                <EmptyState title={t("console.connector.runsEmpty")} />
              </TableEmptyRow>
            ) : (
              runs.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>{formatDateTime(run.started_at)}</TableCell>
                  <TableCell>{runTriggerLabel(t, run.trigger)}</TableCell>
                  <TableCell>
                    <Badge tone={RUN_STATUS_TONES[run.status] ?? "neutral"}>
                      {runStatusLabel(t, run.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <code className="text-xs text-ink-soft">
                      {formatRunStats(run.stats)}
                    </code>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-ink-soft">
                      {run.error || "-"}
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </TableRoot>
        <PaginationBar
          pageStart={pageStart}
          pageEnd={pageEnd}
          totalRows={totalRows}
          pageSize={effectivePageSize}
          pageIndex={pageIndex}
          pageCount={pageCount}
          canPreviousPage={pageIndex > 0}
          canNextPage={pageIndex + 1 < pageCount}
          onPageSizeChange={(nextPageSize) => {
            setPage(1);
            setPageSize(nextPageSize);
          }}
          onPreviousPage={() => setPage((current) => Math.max(1, current - 1))}
          onNextPage={() => setPage((current) => current + 1)}
        />
      </TableFrame>
    </PanelSurface>
  );
}

const RUN_STATUS_LABEL_KEYS: Record<string, MessageKey> = {
  success: "console.connector.status.success",
  partial: "console.connector.status.partial",
  failed: "console.connector.status.failed",
};

function runStatusLabel(t: Translator, status: string): string {
  const labelKey = RUN_STATUS_LABEL_KEYS[status];
  return labelKey ? t(labelKey) : status;
}

function runTriggerLabel(t: Translator, trigger: string): string {
  const labelKey = RUN_TRIGGER_LABEL_KEYS[trigger];
  return labelKey ? t(labelKey) : trigger;
}

function formatRunStats(stats: Record<string, number>): string {
  const entries = Object.entries(stats);
  if (entries.length === 0) {
    return "-";
  }
  return entries.map(([key, count]) => `${key}=${count}`).join(" ");
}

function connectorCandidateFingerprint(
  connectorKey: string,
  instanceId: number | null,
  config: JsonObject,
): string {
  return stableJson({ connectorKey, instanceId, config });
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
