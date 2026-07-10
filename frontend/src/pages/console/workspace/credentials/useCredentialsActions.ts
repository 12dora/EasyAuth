import { useMutation } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { apiRequest } from "../../../../lib/api";
import { credentialDisablePathSegment } from "../../../../lib/credentials";
import type { CredentialItem, SecretPayload } from "../../../../lib/domain";
import { queryClient } from "../../../../lib/query";

type CreateCredentialKind = "static-tokens" | "oauth-clients";

interface CreateCredentialInput {
  kind: CreateCredentialKind;
  name: string;
}

interface CredentialsMutations {
  createSecretMutation: UseMutationResult<SecretPayload, Error, CreateCredentialInput>;
  rotateMutation: UseMutationResult<SecretPayload, Error, CredentialItem>;
  disableMutation: UseMutationResult<unknown, Error, CredentialItem>;
}

interface CredentialsActions {
  createCredential: (kind: CreateCredentialKind, name: string) => Promise<SecretPayload>;
  isCreating: boolean;
  rotateCredential: (credential: CredentialItem) => void;
  disableCredential: (credential: CredentialItem) => void;
  isCredentialPending: (credential: CredentialItem) => boolean;
  operationError: Error | null;
  secretEntries: [string, string][];
  closeSecretDialog: () => void;
}

export function useCredentialsActions(appKey: string): CredentialsActions {
  const [secrets, setSecrets] = useState<SecretPayload[]>([]);
  const [, setPendingCredentialKeys] = useState<Set<string>>(() => new Set());
  const pendingCredentialKeysRef = useRef<Set<string>>(new Set());
  const credentialsQueryKey = ["console", "app", appKey, "credentials"];

  const invalidateCredentials = () => {
    void queryClient.invalidateQueries({ queryKey: credentialsQueryKey });
  };

  const enqueueSecret = (secret: SecretPayload) => {
    setSecrets((current) => [...current, secret]);
  };
  const finishCredentialOperation = (credential: CredentialItem) => {
    const next = new Set(pendingCredentialKeysRef.current);
    next.delete(credentialOperationKey(credential));
    pendingCredentialKeysRef.current = next;
    setPendingCredentialKeys(next);
  };
  const mutations = useCredentialMutations(appKey, enqueueSecret, invalidateCredentials, finishCredentialOperation);

  const beginCredentialOperation = (credential: CredentialItem): boolean => {
    const operationKey = credentialOperationKey(credential);
    if (pendingCredentialKeysRef.current.has(operationKey)) {
      return false;
    }
    const next = new Set(pendingCredentialKeysRef.current);
    next.add(operationKey);
    pendingCredentialKeysRef.current = next;
    setPendingCredentialKeys(next);
    return true;
  };

  return buildCredentialsActions(
    secrets,
    setSecrets,
    (credential) => pendingCredentialKeysRef.current.has(credentialOperationKey(credential)),
    beginCredentialOperation,
    mutations,
  );
}

function useCredentialMutations(
  appKey: string,
  enqueueSecret: (secret: SecretPayload) => void,
  invalidateCredentials: () => void,
  finishCredentialOperation: (credential: CredentialItem) => void,
): CredentialsMutations {
  const createSecretMutation = useMutation({
    mutationFn: ({ kind, name }: CreateCredentialInput) =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/${kind}`, {
        method: "POST",
        body: { name },
      }),
    onSuccess: (payload) => {
      enqueueSecret(payload);
      invalidateCredentials();
    },
  });

  const rotateMutation = useMutation({
    mutationFn: (credential: CredentialItem) =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/static-tokens/${credential.id}/rotate`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      enqueueSecret(payload);
      invalidateCredentials();
    },
    onSettled: (_payload, _error, credential) => finishCredentialOperation(credential),
  });

  const disableMutation = useMutation({
    mutationFn: (credential: CredentialItem) => {
      const kind = credentialDisablePathSegment(credential.kind);
      return apiRequest(`/console/api/v1/apps/${appKey}/credentials/${kind}/${credential.id}/disable`, {
        method: "POST",
        body: {},
      });
    },
    onSuccess: invalidateCredentials,
    onSettled: (_payload, _error, credential) => finishCredentialOperation(credential),
  });

  return { createSecretMutation, rotateMutation, disableMutation };
}

function buildCredentialsActions(
  secrets: SecretPayload[],
  setSecrets: React.Dispatch<React.SetStateAction<SecretPayload[]>>,
  isCredentialPending: (credential: CredentialItem) => boolean,
  beginCredentialOperation: (credential: CredentialItem) => boolean,
  mutations: CredentialsMutations,
): CredentialsActions {
  const secret = secrets[0];
  return {
    createCredential: (kind: CreateCredentialKind, name: string) => mutations.createSecretMutation.mutateAsync({ kind, name }),
    isCreating: mutations.createSecretMutation.isPending,
    rotateCredential: (credential: CredentialItem) => {
      if (beginCredentialOperation(credential)) {
        mutations.rotateMutation.mutate(credential);
      }
    },
    disableCredential: (credential: CredentialItem) => {
      if (beginCredentialOperation(credential)) {
        mutations.disableMutation.mutate(credential);
      }
    },
    isCredentialPending,
    operationError: mutations.createSecretMutation.error ?? mutations.rotateMutation.error ?? mutations.disableMutation.error,
    secretEntries: Object.entries(secret?.one_time_secret ?? {}).filter(([key]) => key !== "kind"),
    closeSecretDialog: () => {
      setSecrets((current) => current.slice(1));
      mutations.createSecretMutation.reset();
      mutations.rotateMutation.reset();
    },
  };
}

function credentialOperationKey(credential: CredentialItem): string {
  return `${credential.kind}:${credential.id}`;
}
