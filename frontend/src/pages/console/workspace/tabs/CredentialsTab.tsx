import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { AppTable } from "../../../../components/antd/AppTable";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useToast } from "../../../../components/ui/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { AppCapabilityKey, CredentialItem } from "../../../../lib/domain";
import { credentialDisablePathSegment } from "../../../../lib/credentials";
import { useI18n } from "../../../../i18n/I18nProvider";
import { useCredentialsActions } from "../credentials/useCredentialsActions";
import { invalidateAppDerivedQueries } from "../invalidateAppQueries";
import { CreateCredentialDialog, CredentialSecretDialog, EditCapabilitiesDialog } from "./CredentialDialogs";
import { buildCredentialColumns } from "./credentialsTabColumns";

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
  const credentialColumns = buildCredentialColumns({
    canManage,
    t,
    isCredentialPending,
    onEditCapabilities: (credential) => {
      setEditingCredential(credential);
      setEditingCapabilities(credential.capabilities ?? []);
    },
    onRotate: rotateCredential,
    onDisable: disableCredential,
  });

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
      <CreateCredentialDialog
        open={createDialogOpen}
        isCreating={isCreating}
        onClose={() => setCreateDialogOpen(false)}
        onCreateCredential={createCredential}
      />
      <CredentialSecretDialog secretEntries={secretEntries} onClose={closeSecretDialog} />
      <EditCapabilitiesDialog
        credential={editingCredential}
        capabilities={editingCapabilities}
        saving={capabilitiesMutation.isPending}
        onCapabilitiesChange={setEditingCapabilities}
        onClose={() => setEditingCredential(null)}
        onSave={() => {
          if (!editingCredential) {
            return;
          }
          capabilitiesMutation.mutate({ credential: editingCredential, capabilities: editingCapabilities });
        }}
      />
    </section>
  );
}
