import { useState } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { ApiError, apiRequest } from "../../lib/api";
import { isWebAuthnAvailable, parseCreationOptions, serializeRegistrationCredential } from "../../lib/webauthn";
import { formatDate, BASE_URL, type PasskeyItem, type Translate, type TwoFactorStatus } from "./twoFactorModel";
import { useTwoFactorSubmit } from "./useTwoFactorSubmit";

export function PasskeyRow({
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
    <div className="py-4 last:pb-0" data-test-id="passkeys-card">
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
            <PasskeyListItem key={passkey.id} t={t} passkey={passkey} onRemove={() => setRemoveTarget(passkey)} />
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

function PasskeyListItem({ t, passkey, onRemove }: { t: Translate; passkey: PasskeyItem; onRemove: () => void }) {
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-2 py-2.5 last:pb-0"
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
        onClick={onRemove}
        data-test-id={`passkey-delete-btn-${passkey.id}`}
      >
        {t("settings.twoFactor.removePasskey")}
      </Button>
    </li>
  );
}

/** 注册通行密钥的失败分三类: 后端拒绝原样透出, 浏览器取消是用户主动放弃, 其余是注册流程失败。 */
function registerErrorMessage(t: Translate) {
  return (caught: unknown) => {
    if (caught instanceof ApiError) {
      return caught.message;
    }
    if (caught instanceof DOMException) {
      return t("settings.twoFactor.passkeyCancelled");
    }
    return t("settings.twoFactor.passkeyFailed");
  };
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
  const submit = useTwoFactorSubmit();

  const confirm = async () => {
    await submit.run(async () => {
      const begin = await apiRequest<{ options: Record<string, unknown>; state_token: string }>(
        `${BASE_URL}/passkeys/register/begin`,
        { method: "POST" },
      );
      const credential = (await navigator.credentials.create({
        publicKey: parseCreationOptions(begin.options as never),
      })) as PublicKeyCredential | null;
      if (!credential) {
        submit.setError(t("settings.twoFactor.passkeyCancelled"));
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
    }, registerErrorMessage(t));
  };

  return (
    <Dialog
      title={t("settings.twoFactor.addPasskeyTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submit.busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="primary" loading={submit.busy} onClick={() => void confirm()} data-test-id="passkey-add-confirm">
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
        {submit.error ? <StatusBanner live="alert" tone="signal" title={submit.error} /> : null}
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
  const submit = useTwoFactorSubmit();

  const confirm = async () => {
    // BS-14: 删除通行密钥(移除第二因子)需 step-up 重认证, DELETE 请求体附带 current_password。
    await submit.run(async () => {
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/passkeys/${passkey.id}`, {
        method: "DELETE",
        body: { current_password: currentPassword },
      });
      onStatus(next);
      onClose();
    }, (caught) => (caught instanceof ApiError ? caught.message : t("settings.twoFactor.genericError")));
  };

  return (
    <Dialog
      title={t("settings.twoFactor.removePasskeyTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submit.busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="danger" loading={submit.busy} onClick={() => void confirm()} data-test-id="passkey-delete-confirm">
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
        {submit.error ? <StatusBanner live="alert" tone="signal" title={submit.error} /> : null}
      </div>
    </Dialog>
  );
}
