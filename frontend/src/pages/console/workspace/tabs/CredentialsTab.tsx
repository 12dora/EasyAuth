import { useQuery } from "@tanstack/react-query";

import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { CredentialItem } from "../../../../lib/domain";
import { CreateCredentialForm } from "../credentials/CreateCredentialForm";
import { CredentialTable } from "../credentials/CredentialTable";
import { useCredentialsActions } from "../credentials/useCredentialsActions";

export function CredentialsTab({ appKey }: { appKey: string }) {
  const credentialsQuery = useQuery({
    queryKey: ["console", "app", appKey, "credentials"],
    queryFn: () => apiRequest<{ items?: CredentialItem[] }>(`/console/api/v1/apps/${appKey}/credentials`),
  });
  const credentials = itemsFromPayload<CredentialItem>(credentialsQuery.data);
  const { createCredential, rotateCredential, disableCredential, operationError, secretEntries, closeSecretDialog } =
    useCredentialsActions(appKey);

  return (
    <section className="stack">
      <CreateCredentialForm onCreateCredential={createCredential} />
      {operationError ? (
        <StatusBanner tone="danger" title="凭据操作失败" message={(operationError as Error).message} />
      ) : null}
      <CredentialTable
        credentials={credentials}
        isLoading={credentialsQuery.isLoading}
        onRotateStaticToken={rotateCredential}
        onDisableCredential={disableCredential}
      />
      {secretEntries[0] ? (
        <SecretDialog
          title="一次性凭据"
          primaryLabel={secretEntries[0][0]}
          primaryValue={secretEntries[0][1]}
          secondaryLabel={secretEntries[1]?.[0]}
          secondaryValue={secretEntries[1]?.[1]}
          onClose={closeSecretDialog}
        />
      ) : null}
    </section>
  );
}
