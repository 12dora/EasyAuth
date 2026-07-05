import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useI18n } from "../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../lib/api";
import {
  isWebAuthnAvailable,
  parseCreationOptions,
  serializeRegistrationCredential,
} from "../../lib/webauthn";

interface PasskeyItem {
  id: number;
  name: string;
  created_at: string | null;
  last_used_at: string | null;
}

interface TwoFactorStatus {
  supported: boolean;
  totp: { enabled: boolean };
  passkeys: PasskeyItem[];
}

interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

type Translate = ReturnType<typeof useI18n>["t"];

const TWO_FACTOR_KEY = ["console", "security", "two-factor"];
const BASE_URL = "/console/api/v1/security/two-factor";

export function TwoFactorSection() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: TWO_FACTOR_KEY,
    queryFn: () => apiRequest<TwoFactorStatus>(BASE_URL),
  });
  const status = statusQuery.data;

  // 未加载完成或非本地管理员(OIDC 管理员的两步验证由上游 Authentik 管理)时不渲染。
  if (!status || !status.supported) {
    return null;
  }

  const applyStatus = (next: TwoFactorStatus) => {
    queryClient.setQueryData(TWO_FACTOR_KEY, next);
  };

  return (
    <PanelSurface padding="lg" className="space-y-1" data-test-id="two-factor-card">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink" data-test-id="two-factor-title">
          {t("settings.twoFactor.title")}
        </h2>
      </div>
      <div className="mt-4 divide-y divide-ink/10 border-t border-ink/10">
        <TotpRow t={t} enabled={status.totp.enabled} onStatus={applyStatus} />
        <PasskeyRow t={t} passkeys={status.passkeys} onStatus={applyStatus} />
      </div>
    </PanelSurface>
  );
}

function TotpRow({ t, enabled, onStatus }: { t: Translate; enabled: boolean; onStatus: (next: TwoFactorStatus) => void }) {
  const [beginning, setBeginning] = useState(false);
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [disableOpen, setDisableOpen] = useState(false);
  const [error, setError] = useState("");

  const openEnroll = async () => {
    if (beginning) {
      return;
    }
    setError("");
    setBeginning(true);
    try {
      const data = await apiRequest<TotpSetup>(`${BASE_URL}/totp/begin`, { method: "POST" });
      setSetup(data);
    } catch (caught) {
      // FF-3: /totp/begin 失败不再静默丢弃, 把后端错误(中文)显式呈现给用户。
      setError(caught instanceof ApiError ? caught.message : t("settings.twoFactor.genericError"));
    } finally {
      setBeginning(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-4" data-test-id="totp-method">
      <div className="min-w-0">
        <p className="text-body text-ink">{t("settings.twoFactor.authenticator")}</p>
        <p className="mt-0.5 text-xs text-ink-faint">
          {enabled ? t("settings.twoFactor.enabled") : t("settings.twoFactor.authenticatorHint")}
        </p>
      </div>
      {enabled ? (
        <Button variant="ghost" onClick={() => setDisableOpen(true)} data-test-id="totp-disable-btn">
          {t("settings.twoFactor.disable")}
        </Button>
      ) : (
        <Button variant="ghost" loading={beginning} onClick={() => void openEnroll()} data-test-id="totp-enable-btn">
          {t("settings.twoFactor.enable")}
        </Button>
      )}
      {error ? (
        <div className="w-full">
          <StatusBanner tone="signal" title={error} />
        </div>
      ) : null}
      {setup ? (
        <TotpEnrollDialog t={t} setup={setup} onClose={() => setSetup(null)} onStatus={onStatus} />
      ) : null}
      {disableOpen ? (
        <TotpDisableDialog t={t} onClose={() => setDisableOpen(false)} onStatus={onStatus} />
      ) : null}
    </div>
  );
}

function TotpEnrollDialog({
  t,
  setup,
  onClose,
  onStatus,
}: {
  t: Translate;
  setup: TotpSetup;
  onClose: () => void;
  onStatus: (next: TwoFactorStatus) => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const confirm = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/totp/confirm`, {
        method: "POST",
        body: { code: code.trim() },
      });
      onStatus(next);
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t("settings.twoFactor.genericError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={t("settings.twoFactor.enableTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void confirm()} data-test-id="totp-confirm-btn">
            {t("settings.twoFactor.confirmEnable")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-test-id="totp-enroll-dialog">
        <p className="text-body text-ink-soft">{t("settings.twoFactor.scanQr")}</p>
        <div className="flex justify-center rounded-[3px] border border-dashed border-ink/20 bg-paper-deep/40 p-4">
          <img src={setup.qr_svg} alt={t("settings.twoFactor.scanQr")} className="size-40" />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-label uppercase tracking-caps-wide text-ink-soft">
            {t("settings.twoFactor.manualEntry")}
          </span>
          <code className="break-all rounded-[2px] bg-paper-deep/60 px-2 py-1 font-mono text-body text-ink">
            {setup.secret}
          </code>
        </div>
        <Field label={t("settings.twoFactor.currentCode")}>
          <TextInput
            id="totp-enroll-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(event) => setCode(event.currentTarget.value)}
            className="text-center font-mono tracking-[0.4em]"
          />
        </Field>
        {error ? <StatusBanner tone="signal" title={error} /> : null}
      </div>
    </Dialog>
  );
}

function TotpDisableDialog({
  t,
  onClose,
  onStatus,
}: {
  t: Translate;
  onClose: () => void;
  onStatus: (next: TwoFactorStatus) => void;
}) {
  const [code, setCode] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const confirm = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      // BS-14: 停用第二因子需 step-up 重认证, 请求体附带 current_password。
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/totp/disable`, {
        method: "POST",
        body: { code: code.trim(), current_password: currentPassword },
      });
      onStatus(next);
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t("settings.twoFactor.genericError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={t("settings.twoFactor.disableTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void confirm()} data-test-id="totp-disable-confirm">
            {t("settings.twoFactor.confirmDisable")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-body text-ink-soft">{t("settings.twoFactor.disableHint")}</p>
        <Field label={t("settings.twoFactor.currentCode")}>
          <TextInput
            id="totp-disable-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(event) => setCode(event.currentTarget.value)}
            className="text-center font-mono tracking-[0.4em]"
          />
        </Field>
        <Field label={t("settings.twoFactor.currentPassword")} hint={t("settings.twoFactor.currentPasswordHint")}>
          <TextInput
            id="totp-disable-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.currentTarget.value)}
          />
        </Field>
        {error ? <StatusBanner tone="signal" title={error} /> : null}
      </div>
    </Dialog>
  );
}

function PasskeyRow({
  t,
  passkeys,
  onStatus,
}: {
  t: Translate;
  passkeys: PasskeyItem[];
  onStatus: (next: TwoFactorStatus) => void;
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<PasskeyItem | null>(null);
  const webAuthnAvailable = isWebAuthnAvailable();

  return (
    <div className="py-4" data-test-id="passkeys-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-body text-ink" data-test-id="passkeys-title">
            {t("settings.twoFactor.passkeys")}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">{t("settings.twoFactor.passkeysHint")}</p>
        </div>
        <Button
          variant="ghost"
          disabled={!webAuthnAvailable}
          title={webAuthnAvailable ? undefined : t("settings.twoFactor.passkeyUnsupported")}
          onClick={() => setAddOpen(true)}
          data-test-id="passkey-add-btn"
        >
          {t("settings.twoFactor.addPasskey")}
        </Button>
      </div>
      {!webAuthnAvailable ? (
        <p className="mt-2 text-xs text-signal">{t("settings.twoFactor.passkeyUnsupported")}</p>
      ) : null}
      {passkeys.length === 0 ? (
        <p className="mt-3 text-body text-ink-soft" data-test-id="passkeys-empty">
          {t("settings.twoFactor.passkeysEmpty")}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-ink/10 border-t border-ink/10" data-test-id="passkeys-list">
          {passkeys.map((passkey) => (
            <li
              key={passkey.id}
              className="flex flex-wrap items-center justify-between gap-2 py-2.5"
              data-test-id={`passkey-row-${passkey.id}`}
            >
              <div className="min-w-0">
                <p className="truncate text-body text-ink">{passkey.name || t("settings.twoFactor.passkeyUnnamed")}</p>
                <p className="mt-0.5 text-micro text-ink-faint">
                  {t("settings.twoFactor.passkeyCreatedAt")} {formatDate(passkey.created_at)} ·{" "}
                  {t("settings.twoFactor.passkeyLastUsedAt")}{" "}
                  {passkey.last_used_at ? formatDate(passkey.last_used_at) : t("settings.twoFactor.passkeyNeverUsed")}
                </p>
              </div>
              <Button
                variant="ghost-danger"
                size="sm"
                onClick={() => setRemoveTarget(passkey)}
                data-test-id={`passkey-delete-btn-${passkey.id}`}
              >
                {t("settings.twoFactor.removePasskey")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {addOpen ? <AddPasskeyDialog t={t} onClose={() => setAddOpen(false)} onStatus={onStatus} /> : null}
      {removeTarget ? (
        <RemovePasskeyDialog
          t={t}
          passkey={removeTarget}
          onClose={() => setRemoveTarget(null)}
          onStatus={onStatus}
        />
      ) : null}
    </div>
  );
}

function AddPasskeyDialog({
  t,
  onClose,
  onStatus,
}: {
  t: Translate;
  onClose: () => void;
  onStatus: (next: TwoFactorStatus) => void;
}) {
  const [name, setName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const confirm = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const begin = await apiRequest<{ options: Record<string, unknown>; state_token: string }>(
        `${BASE_URL}/passkeys/register/begin`,
        { method: "POST" },
      );
      const credential = (await navigator.credentials.create({
        publicKey: parseCreationOptions(begin.options as never),
      })) as PublicKeyCredential | null;
      if (!credential) {
        setError(t("settings.twoFactor.passkeyCancelled"));
        return;
      }
      // BS-14: 注册通行密钥(新增第二因子)需 step-up 重认证, 请求体附带 current_password。
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/passkeys/register/complete`, {
        method: "POST",
        body: {
          credential: serializeRegistrationCredential(credential),
          state_token: begin.state_token,
          name: name.trim(),
          current_password: currentPassword,
        },
      });
      onStatus(next);
      onClose();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
      } else if (caught instanceof DOMException) {
        setError(t("settings.twoFactor.passkeyCancelled"));
      } else {
        setError(t("settings.twoFactor.passkeyFailed"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={t("settings.twoFactor.addPasskeyTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void confirm()} data-test-id="passkey-add-confirm">
            {t("settings.twoFactor.startVerification")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-test-id="passkey-add-dialog">
        <p className="text-body text-ink-soft">{t("settings.twoFactor.addPasskeyHint")}</p>
        <Field label={t("settings.twoFactor.passkeyName")}>
          <TextInput
            id="passkey-name"
            maxLength={64}
            value={name}
            placeholder={t("settings.twoFactor.passkeyNamePlaceholder")}
            onChange={(event) => setName(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("settings.twoFactor.currentPassword")} hint={t("settings.twoFactor.currentPasswordHint")}>
          <TextInput
            id="passkey-add-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.currentTarget.value)}
          />
        </Field>
        {error ? <StatusBanner tone="signal" title={error} /> : null}
      </div>
    </Dialog>
  );
}

function RemovePasskeyDialog({
  t,
  passkey,
  onClose,
  onStatus,
}: {
  t: Translate;
  passkey: PasskeyItem;
  onClose: () => void;
  onStatus: (next: TwoFactorStatus) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const confirm = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      // BS-14: 删除通行密钥(移除第二因子)需 step-up 重认证, DELETE 请求体附带 current_password。
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/passkeys/${passkey.id}`, {
        method: "DELETE",
        body: { current_password: currentPassword },
      });
      onStatus(next);
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t("settings.twoFactor.genericError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={t("settings.twoFactor.removePasskeyTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void confirm()} data-test-id="passkey-delete-confirm">
            {t("settings.twoFactor.confirmRemove")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-body text-ink-soft">
          {t("settings.twoFactor.removePasskeyConfirm").replace(
            "{name}",
            passkey.name || t("settings.twoFactor.passkeyUnnamed"),
          )}
        </p>
        <Field label={t("settings.twoFactor.currentPassword")} hint={t("settings.twoFactor.currentPasswordHint")}>
          <TextInput
            id="passkey-remove-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.currentTarget.value)}
          />
        </Field>
        {error ? <StatusBanner tone="signal" title={error} /> : null}
      </div>
    </Dialog>
  );
}

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleDateString();
}
