export function credentialDisablePathSegment(kind: string): string {
  switch (kind) {
    case "static_token":
      return "static-tokens";
    case "oauth_client":
      return "oauth-clients";
    default:
      return `${kind}s`;
  }
}
