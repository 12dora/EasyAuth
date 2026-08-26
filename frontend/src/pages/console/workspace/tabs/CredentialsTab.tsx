import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { AppTable, enumFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import { actionsColumn, textColumn } from "../../../../components/antd/columns";
import { EmptyState } from "../../../../components/ui/EmptyState";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useToast } from "../../../../components/ui/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppCapabilityKey, CredentialItem } from "../../../../lib/domain";
import { credentialDisablePathSegment } from "../../../../lib/credentials";
import { useI18n } from "../../../../i18n/I18nProvider";
import { CreateCredentialForm } from "../credentials/CreateCredentialForm";
import { useCredentialsActions } from "../credentials/useCredentialsActions";
import { invalidateAppDerivedQueries } from "../invalidateAppQueries";
import { credentialKindLabel } from "../utils";
import { activeStatusColumn, RowActionButton } from "../workspaceColumns";

export function CredentialsTab({ appKey, canManage }: { appKey: string; canManage: boolean }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingCredential, setEditingCredential] = useState<CredentialItem | null>(null);
  const [editingCapabilities, setEditingCapabilities] = useState<AppCapabilityKey[]>([]);
  const credentialsQuery = useQuery({
    queryKey: ["console", "app", appKey, "credentials"],
    queryFn: () => apiRequest<ListPayload<CredentialItem>>(`/console/api/v1/apps/${appKey}/credentials`),
  });
  const credentials = itemsFromPayload<CredentialItem>(credentialsQuery.data);
  const capabilitiesMutation = useMutation({
    mutationFn: ({ credential, capabilities }: { credential: CredentialItem; capabilities: AppCapabilityKey[] }) =>
      apiRequest(`/console/api/v1/apps/${appKey}/credentials/${credentialDisablePathSegment(credential.kind)}/${credential.id}/capabilities`, {
        method: "PUT",
        body: { capabilities },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "credentials"] });
      invalidateAppDerivedQueries(queryClient, appKey);
      setEditingCredential(null);
      toast.success(t("console.credentials.capabilitiesSaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.credentials.capabilitiesSaveFailed"), error.message);
    },
  });
  const { createCredential, isCreating, rotateCredential, disableCredential, isCredentialPending, operationError, secretEntries, closeSecretDialog } =
    useCredentialsActions(appKey);
  // 创建/轮换/停用等操作失败时以 toast 反馈, 替代原先的页面内联横幅。
  useEffect(() => {
    if (operationError) {
      toast.error(t("console.credentials.operationFailed"), operationError.message);
    }
  }, [operationError, toast, t]);
  const credentialColumns: ColumnsType<CredentialItem> = [
    textColumn<CredentialItem>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    {
      key: "kind",
      dataIndex: "kind",
      title: t("common.type"),
      width: 140,
      render: (_value: unknown, credential: CredentialItem) => credentialKindLabel(credential.kind),
      ...enumFilter<CredentialItem>("kind", [
        { label: credentialKindLabel("static_token"), value: "static_token" },
        { label: credentialKindLabel("oauth_client"), value: "oauth_client" },
      ]),
    },
    textColumn<CredentialItem>({ key: "client_id", title: "client_id", mono: true, filter: true, width: 220 }),
    {
      key: "capabilities",
      title: t("console.credentials.capabilities"),
      width: 200,
      render: (_value: unknown, credential: CredentialItem) => (
        <div className="flex min-w-36 flex-wrap gap-1">
          {(credential.capabilities ?? []).length > 0 ? (
            credential.capabilities?.map((capability) => <Badge key={capability} tone="bond">{capability}</Badge>)
          ) : (
            <Badge tone="faint">{t("console.credentials.permissionOnly")}</Badge>
          )}
        </div>
      ),
      // 能力是多值, 未授予任何能力的凭据归到「仅权限查询」这一档。
      ...enumFilter<CredentialItem>(
        "capabilities",
        [
          { label: "directory", value: "directory" },
          { label: "notify", value: "notify" },
          { label: t("console.credentials.permissionOnly"), value: "none" },
        ],
        {
          getValue: (credential) => ((credential.capabilities ?? []).length > 0 ? (credential.capabilities ?? []) : ["none"]),
        },
      ),
    },
    activeStatusColumn<CredentialItem>({ t, getActive: (credential) => credential.is_active }),
    actionsColumn<CredentialItem>({
      title: t("common.actions"),
      render: (credential) => (
        <>
          {canManage ? (
            <RowActionButton
              type="button"
              disabled={isCredentialPending(credential)}
              onClick={() => {
                setEditingCredential(credential);
                setEditingCapabilities(credential.capabilities ?? []);
              }}
            >
              <Pencil size={13} aria-hidden="true" />
              {t("console.credentials.editCapabilities")}
            </RowActionButton>
          ) : null}
          {canManage && credential.kind === "static_token" ? (
            <RowActionButton
              type="button"
              disabled={isCredentialPending(credential)}
              onClick={() => rotateCredential(credential)}
            >
              {t("console.credentials.rotate")}
            </RowActionButton>
          ) : null}
          {canManage ? (
            <RowActionButton
              type="button"
              variant="ghost-danger"
              disabled={isCredentialPending(credential)}
              onClick={() => disableCredential(credential)}
            >
              {t("console.credentials.disable")}
            </RowActionButton>
          ) : <span className="text-xs text-ink-faint">{t("console.integration.readOnlyMode")}</span>}
        </>
      ),
    }),
  ];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-ink">{t("console.credentials.heading")}</h2>
          <p className="text-body leading-5 text-ink-soft">{t("console.credentials.description")}</p>
        </div>
        {canManage ? (
          <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
            {t("common.new")}
          </Button>
        ) : <Badge>{t("console.integration.readOnlyMode")}</Badge>}
      </div>
      <StatusBanner
        tone="bond"
        title={t("console.credentials.permissionBoundaryTitle")}
        message={t("console.credentials.permissionBoundaryDescription")}
      />
      {credentialsQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("console.credentials.loadFailed")} message={(credentialsQuery.error as Error).message} />
      ) : null}
      <AppTable<CredentialItem>
        columns={credentialColumns}
        dataSource={credentials}
        rowKey={(credential) => `${credential.kind}:${credential.id}`}
        loading={credentialsQuery.isLoading}
        minWidth={1080}
        empty={<EmptyState title={t("console.credentials.empty")} description={t("console.credentials.emptyDescription")} />}
      />
      {createDialogOpen ? (
        <Dialog title={t("console.credentials.createTitle")} onClose={() => setCreateDialogOpen(false)}>
          <CreateCredentialForm
            isCreating={isCreating}
            onCreateCredential={async (kind, name, capabilities) => {
              await createCredential(kind, name, capabilities);
              setCreateDialogOpen(false);
            }}
          />
        </Dialog>
      ) : null}
      {secretEntries[0] ? (
        <SecretDialog
          title={t("console.credentials.secretTitle")}
          primaryLabel={secretEntries[0][0]}
          primaryValue={secretEntries[0][1]}
          secondaryLabel={secretEntries[1]?.[0]}
          secondaryValue={secretEntries[1]?.[1]}
          onClose={closeSecretDialog}
        />
      ) : null}
      {editingCredential ? (
        <Dialog title={t("console.credentials.editCapabilitiesTitle")} onClose={() => setEditingCredential(null)}>
          <div className="space-y-5">
            <p className="text-body leading-5 text-ink-soft">
              {t("console.credentials.editCapabilitiesDescription", { name: editingCredential.name })}
            </p>
            <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label={t("console.credentials.capabilities")}>
              {(["directory", "notify"] as const).map((capability) => (
                <label key={capability} className="flex items-center gap-2 border border-ink/12 bg-paper-soft px-3 py-2 text-body text-ink">
                  <input
                    type="checkbox"
                    checked={editingCapabilities.includes(capability)}
                    onChange={(event) => {
                      const checked = event.currentTarget.checked;
                      setEditingCapabilities((current) => checked
                        ? [...current, capability]
                        : current.filter((item) => item !== capability));
                    }}
                  />
                  <code>{capability}</code>
                </label>
              ))}
            </div>
            <StatusBanner tone="amber" title={t("console.credentials.capabilityWarningTitle")} message={t("console.credentials.capabilityWarningDescription")} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={() => setEditingCredential(null)}>{t("common.cancel")}</Button>
              <Button
                type="button"
                variant="primary"
                loading={capabilitiesMutation.isPending}
                onClick={() => capabilitiesMutation.mutate({ credential: editingCredential, capabilities: editingCapabilities })}
              >
                {t("console.credentials.saveCapabilities")}
              </Button>
            </div>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
