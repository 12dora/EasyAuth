// WebAuthn 浏览器端辅助: base64url 编解码 + 注册 options/credential 的解析与序列化。
// 与后端 py_webauthn 的 options_to_json / verify_registration_response 约定对齐。
import type { JsonObject } from "./api";

export function isWebAuthnAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    Boolean(navigator.credentials?.create)
  );
}

export function base64urlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padLength = (4 - (normalized.length % 4)) % 4;
  const base64 = normalized + "=".repeat(padLength);
  const binary = atob(base64);
  const buffer = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

export function bytesToBase64url(buffer: ArrayBuffer): string {
  const view = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < view.length; index += 1) {
    binary += String.fromCharCode(view[index]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface CredentialDescriptorJson {
  id: string;
  type: string;
  transports?: string[];
}

interface RegistrationOptionsJson {
  challenge: string;
  user: { id: string; name: string; displayName: string };
  excludeCredentials?: CredentialDescriptorJson[];
  [key: string]: unknown;
}

export function parseCreationOptions(options: RegistrationOptionsJson): PublicKeyCredentialCreationOptions {
  return {
    ...(options as unknown as PublicKeyCredentialCreationOptions),
    challenge: base64urlToBytes(options.challenge),
    user: {
      ...options.user,
      id: base64urlToBytes(options.user.id),
    },
    excludeCredentials: (options.excludeCredentials ?? []).map((descriptor) => ({
      id: base64urlToBytes(descriptor.id),
      type: descriptor.type as PublicKeyCredentialType,
      transports: descriptor.transports as AuthenticatorTransport[] | undefined,
    })),
  };
}

export function serializeRegistrationCredential(credential: PublicKeyCredential): JsonObject {
  const response = credential.response as AuthenticatorAttestationResponse;
  const transports = typeof response.getTransports === "function" ? response.getTransports() : [];
  return {
    id: credential.id,
    rawId: bytesToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bytesToBase64url(response.clientDataJSON),
      attestationObject: bytesToBase64url(response.attestationObject),
      transports,
    },
    clientExtensionResults: credential.getClientExtensionResults() as unknown as JsonObject,
    authenticatorAttachment: credential.authenticatorAttachment ?? null,
  };
}
