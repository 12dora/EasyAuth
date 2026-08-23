import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { apiRequest } from "../../../lib/api";
import type { SecretPayload } from "../../../lib/domain";
import type { CredentialCreateRequest, CredentialKindPath, CredentialProgress, OAuthExchangeRequest } from "./types";
import { parseCredentialSecretPayload, parseOAuthAccessToken } from "./wizardParsing";

export interface CredentialStepState {
  name: string;
  setName: (name: string) => void;
  secretEntries: Array<[string, string]>;
  credentialPending: boolean;
  continuationBlocked: boolean;
  createError: Error | null;
  exchangeError: Error | null;
  createCredential: (kind: CredentialKindPath) => void;
}

/** 凭据步骤的本地状态机: OAuth 客户端建好后必须再换到 access_token 才算就绪, 期间禁止继续下一步。 */
export function useCredentialStep(
  appKey: string,
  onProgressChange: (progress: CredentialProgress | null) => void,
): CredentialStepState {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<SecretPayload | null>(null);
  const credentialRequestIdRef = useRef(0);
  const exchangeMutation = useMutation({
    mutationFn: async (request: OAuthExchangeRequest) =>
      parseOAuthAccessToken(await apiRequest<unknown>("/oauth/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "client_credentials",
          client_id: request.clientId,
          client_secret: request.clientSecret,
        }),
      })),
    onSuccess: (accessToken, request) => {
      if (request.requestId !== credentialRequestIdRef.current) {
        return;
      }
      setSecret((current) => {
        if (current?.one_time_secret?.client_id !== request.clientId) {
          return current;
        }
        return {
          ...current,
          one_time_secret: { ...current.one_time_secret, access_token: accessToken },
        };
      });
      onProgressChange({ kind: "oauth_client", ready: true });
    },
  });
  const createMutation = useMutation({
    mutationFn: async (request: CredentialCreateRequest) =>
      parseCredentialSecretPayload(
        await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/credentials/${request.kind}`, {
          method: "POST",
          body: { name: request.name },
        }),
        request.kind,
      ),
    onSuccess: (payload, request) => {
      if (request.requestId !== credentialRequestIdRef.current) {
        return;
      }
      setSecret(payload);
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey] });
      if (payload.credential?.kind === "oauth_client") {
        const clientId = payload.one_time_secret?.client_id;
        const clientSecret = payload.one_time_secret?.client_secret;
        exchangeMutation.mutate({ clientId, clientSecret, requestId: request.requestId });
      } else {
        onProgressChange({ kind: "static_token", ready: true });
      }
    },
    onError: (_error, request) => {
      if (request.requestId === credentialRequestIdRef.current) {
        onProgressChange(null);
      }
    },
  });
  const secretEntries = Object.entries(secret?.one_time_secret ?? {}).filter(([key]) => key !== "kind");
  const credentialPending = createMutation.isPending || exchangeMutation.isPending;
  const oauthExchangeIncomplete =
    secret?.credential?.kind === "oauth_client" &&
    typeof secret.one_time_secret?.access_token !== "string";

  const createCredential = (kind: CredentialKindPath) => {
    const requestId = credentialRequestIdRef.current + 1;
    credentialRequestIdRef.current = requestId;
    createMutation.reset();
    exchangeMutation.reset();
    setSecret(null);
    onProgressChange({
      kind: kind === "static-tokens" ? "static_token" : "oauth_client",
      ready: false,
    });
    createMutation.mutate({ kind, name, requestId });
  };

  return {
    name,
    setName,
    secretEntries,
    credentialPending,
    continuationBlocked: credentialPending || oauthExchangeIncomplete,
    createError: createMutation.error,
    exchangeError: exchangeMutation.error,
    createCredential,
  };
}
