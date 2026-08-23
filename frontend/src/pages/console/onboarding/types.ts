import type { MessageKey } from "../../../i18n/messages";

export type WizardStep = "basics" | "catalog" | "authz" | "credential" | "verify" | "done";
export type CreatedCredentialKind = "static_token" | "oauth_client";

export interface CredentialProgress {
  kind: CreatedCredentialKind;
  ready: boolean;
}

export interface WizardStepDescriptor {
  key: WizardStep;
  labelKey: MessageKey;
}

export interface AppSummaryLike {
  app_key: string;
  name: string;
  description?: string;
  owners?: string[];
}

export interface AutoOnboardingResult {
  app_key: string;
  app_name: string;
  created: boolean;
  already_up_to_date: boolean;
  template_version: number;
  catalog_version: number | string;
}

export interface AutoOnboardingRequest {
  baseUrl: string;
  appKey: string;
  descriptorToken: string;
  requestId: number;
}

export type ManifestPreviewPayload = {
  diff?: {
    added?: ManifestDiffItem[];
    changed?: ManifestDiffItem[];
    removed?: ManifestDiffItem[];
  };
  changes?: Array<{ action?: string; key?: string; parent_key?: string }>;
  preview_id?: string;
};

export type ManifestDiffItem = {
  type?: string;
  key?: string;
  name?: string;
  before?: unknown;
  after?: unknown;
};

export interface ManifestPreviewSnapshot {
  payload: ManifestPreviewPayload;
  contentFingerprint: string;
  requestId: number;
}

export interface ManifestPreviewRequest {
  content: string;
  contentFingerprint: string;
  requestId: number;
}

export interface ManifestImportRequest {
  previewId: string;
  contentFingerprint: string;
  requestId: number;
}

export type CredentialKindPath = "static-tokens" | "oauth-clients";

export interface CredentialCreateRequest {
  kind: CredentialKindPath;
  name: string;
  requestId: number;
}

export interface OAuthExchangeRequest {
  clientId: string;
  clientSecret: string;
  requestId: number;
}

export interface QueryTestRequest {
  userId: string;
  token: string;
  requestId: number;
}
