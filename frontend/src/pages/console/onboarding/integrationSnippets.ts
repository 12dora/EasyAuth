import type { MessageKey } from "../../../i18n/messages";
import type { CreatedCredentialKind } from "./types";

interface IntegrationSnippetInput {
  appKey: string;
  appName: string;
  origin: string;
  credentialKind: CreatedCredentialKind | null;
}

export function buildIntegrationSnippets({ appKey, appName, origin, credentialKind }: IntegrationSnippetInput): {
  integrationSnippet: string;
  curlSnippet: string;
} {
  const endpoint = `${origin}/api/v1/apps/${appKey}/users/{user_id}/permissions`;
  const tokenPlaceholder =
    credentialKind === "oauth_client"
      ? "<access_token>"
      : credentialKind === "static_token"
        ? "<app_token>"
        : "<bearer_token>";
  const tokenEnvironmentVariable = credentialKind === "oauth_client" ? "$ACCESS_TOKEN" : "$APP_TOKEN";
  return {
    integrationSnippet: [
      `# ${appName}`,
      `EASYAUTH_BASE_URL=${origin}`,
      `EASYAUTH_APP_KEY=${appKey}`,
      "",
      `GET ${endpoint}`,
      `Authorization: Bearer ${tokenPlaceholder}`,
    ].join("\n"),
    curlSnippet: `curl -H "Authorization: Bearer ${tokenEnvironmentVariable}" "${endpoint}"`,
  };
}

export function integrationHintKey(credentialKind: CreatedCredentialKind | null): MessageKey {
  if (credentialKind === "oauth_client") {
    return "wizard.done.integrationHint.oauth";
  }
  return credentialKind === "static_token" ? "wizard.done.integrationHint.static" : "wizard.done.integrationHint.existing";
}
