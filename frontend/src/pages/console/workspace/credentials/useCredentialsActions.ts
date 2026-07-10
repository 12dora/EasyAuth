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
  rotateMutation: UseMutationResult<SecretPayload, Error, number>;
  disableMutation: UseMutationResult<unknown, Error, CredentialItem>;
}

interface CredentialsActions {
  createCredential: (kind: CreateCredentialKind, name: string) => Promise<SecretPayload>;
  isCreating: boolean;
  rotateCredential: (credentialId: number) => void;
  disableCredential: (credential: CredentialItem) => void;
  isCredentialPending: (credentialId: number) => boolean;
  operationError: Error | null;
  secretEntries: [string, string][];
  closeSecretDialog: () => void;
}

export function useCredentialsActions(appKey: string): CredentialsActions {
  const [secrets, setSecrets] = useState<SecretPayload[]>([]);
  const [, setPendingCredentialIds] = useState<Set<number>>(() => new Set());
  const pendingCredentialIdsRef = useRef<Set<number>>(new Set());
  const credentialsQueryKey = ["console", "app", appKey, "credentials"];

  const invalidateCredentials = () => {
    void queryClient.invalidateQueries({ queryKey: credentialsQueryKey });
  };

  const enqueueSecret = (secret: SecretPayload) => {
    setSecrets((current) => [...current, secret]);
  };
  const finishCredentialOperation = (credentialId: number) => {
    const next = new Set(pendingCredentialIdsRef.current);
    next.delete(credentialId);
    pendingCredentialIdsRef.current = next;
    setPendingCredentialIds(next);
  };
  const mutations = useCredentialMutations(appKey, enqueueSecret, invalidateCredentials, finishCredentialOperation);

  const beginCredentialOperation = (credentialId: number): boolean => {
    if (pendingCredentialIdsRef.current.has(credentialId)) {
      return false;
    }
    const next = new Set(pendingCredentialIdsRef.current);
    next.add(credentialId);
    pendingCredentialIdsRef.current = next;
    setPendingCredentialIds(next);
    return true;
  };

  return buildCredentialsActions(
    secrets,
    setSecrets,
    (credentialId) => pendingCredentialIdsRef.current.has(credentialId),
    beginCredentialOperation,
    mutations,
  );
}

function useCredentialMutations(
  appKey: string,
  enqueueSecret: (secret: SecretPayload) => void,
  invalidateCredentials: () => void,
  finishCredentialOperation: (credentialId: number) => void,
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
    mutationFn: (credentialId: number) =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/static-tokens/${credentialId}/rotate`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      enqueueSecret(payload);
      invalidateCredentials();
    },
    onSettled: (_payload, _error, credentialId) => finishCredentialOperation(credentialId),
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
    onSettled: (_payload, _error, credential) => finishCredentialOperation(credential.id),
  });

  return { createSecretMutation, rotateMutation, disableMutation };
}

function buildCredentialsActions(
  secrets: SecretPayload[],
  setSecrets: React.Dispatch<React.SetStateAction<SecretPayload[]>>,
  isCredentialPending: (credentialId: number) => boolean,
  beginCredentialOperation: (credentialId: number) => boolean,
  mutations: CredentialsMutations,
): CredentialsActions {
  const secret = secrets[0];
  return {
    createCredential: (kind: CreateCredentialKind, name: string) => mutations.createSecretMutation.mutateAsync({ kind, name }),
    isCreating: mutations.createSecretMutation.isPending,
    rotateCredential: (credentialId: number) => {
      if (beginCredentialOperation(credentialId)) {
        mutations.rotateMutation.mutate(credentialId);
      }
    },
    disableCredential: (credential: CredentialItem) => {
      if (beginCredentialOperation(credential.id)) {
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
