import { useMutation } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useState } from "react";

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
  rotateCredential: (credentialId: number) => void;
  disableCredential: (credential: CredentialItem) => void;
  operationError: Error | null;
  secretEntries: [string, string][];
  closeSecretDialog: () => void;
}

export function useCredentialsActions(appKey: string): CredentialsActions {
  const [secret, setSecret] = useState<SecretPayload | null>(null);
  const credentialsQueryKey = ["console", "app", appKey, "credentials"];

  const invalidateCredentials = () => {
    void queryClient.invalidateQueries({ queryKey: credentialsQueryKey });
  };

  const mutations = useCredentialMutations(appKey, setSecret, invalidateCredentials);

  return buildCredentialsActions(secret, setSecret, mutations);
}

function useCredentialMutations(
  appKey: string,
  setSecret: (secret: SecretPayload | null) => void,
  invalidateCredentials: () => void,
): CredentialsMutations {
  const createSecretMutation = useMutation({
    mutationFn: ({ kind, name }: CreateCredentialInput) =>
      apiRequest<SecretPayload>(`/console/api/v1/apps/${appKey}/credentials/${kind}`, {
        method: "POST",
        body: { name },
      }),
    onSuccess: (payload) => {
      setSecret(payload);
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
      setSecret(payload);
      invalidateCredentials();
    },
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
  });

  return { createSecretMutation, rotateMutation, disableMutation };
}

function buildCredentialsActions(
  secret: SecretPayload | null,
  setSecret: (secret: SecretPayload | null) => void,
  mutations: CredentialsMutations,
): CredentialsActions {
  return {
    createCredential: (kind: CreateCredentialKind, name: string) => mutations.createSecretMutation.mutateAsync({ kind, name }),
    rotateCredential: (credentialId: number) => mutations.rotateMutation.mutate(credentialId),
    disableCredential: (credential: CredentialItem) => mutations.disableMutation.mutate(credential),
    operationError: mutations.createSecretMutation.error ?? mutations.rotateMutation.error ?? mutations.disableMutation.error,
    secretEntries: Object.entries(secret?.one_time_secret ?? {}).filter(([key]) => key !== "kind"),
    closeSecretDialog: () => {
      setSecret(null);
      mutations.createSecretMutation.reset();
      mutations.rotateMutation.reset();
    },
  };
}
