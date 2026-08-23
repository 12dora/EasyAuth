import type { useI18n } from "../../i18n/I18nProvider";

export interface PasskeyItem {
  id: number;
  name: string;
  created_at: string | null;
  last_used_at: string | null;
}

export interface TwoFactorStatus {
  supported: boolean;
  totp: { enabled: boolean };
  passkeys: PasskeyItem[];
}

export interface TotpSetup {
  enrollment_nonce: string;
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

export type Translate = ReturnType<typeof useI18n>["t"];

export const TWO_FACTOR_KEY = ["console", "security", "two-factor"];
export const BASE_URL = "/console/api/v1/security/two-factor";

export function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleDateString();
}
