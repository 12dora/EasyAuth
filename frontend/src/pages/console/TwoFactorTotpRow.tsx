import { useState } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { ApiError, apiRequest } from "../../lib/api";
import { BASE_URL, type Translate, type TotpSetup, type TwoFactorStatus } from "./twoFactorModel";
import { useTwoFactorSubmit } from "./useTwoFactorSubmit";

/** 非 ApiError(网络/解析异常)没有可展示的后端原因, 统一落到通用错误文案。 */
function genericMessage(t: Translate) {
  return (caught: unknown) => (caught instanceof ApiError ? caught.message : t("settings.twoFactor.genericError"));
}

export function TotpRow({
  t,
  enabled,
  onStatus,
}: {
  t: Translate;
  enabled: boolean;
  onStatus: (next: TwoFactorStatus) => void;
}) {
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [beginOpen, setBeginOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const submit = useTwoFactorSubmit();

  const openEnroll = async (currentPassword: string) => {
    // FF-3: /totp/begin 失败不再静默丢弃, 把后端错误(中文)显式呈现给用户。
    await submit.run(async () => {
      const data = await apiRequest<TotpSetup>(`${BASE_URL}/totp/begin`, {
        method: "POST",
        body: { current_password: currentPassword },
      });
      setSetup(data);
      setBeginOpen(false);
    }, genericMessage(t));
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
        <Button variant="ghost" loading={submit.busy} onClick={() => setBeginOpen(true)} data-test-id="totp-enable-btn">
          {t("settings.twoFactor.enable")}
        </Button>
      )}
      {submit.error && !beginOpen ? (
        <div className="w-full">
          <StatusBanner live="alert" tone="signal" title={submit.error} />
        </div>
      ) : null}
      {setup ? (
        <TotpEnrollDialog t={t} setup={setup} onClose={() => setSetup(null)} onStatus={onStatus} />
      ) : null}
      {beginOpen ? (
        <TotpBeginDialog
          t={t}
          busy={submit.busy}
          error={submit.error}
          onClose={() => setBeginOpen(false)}
          onConfirm={openEnroll}
        />
      ) : null}
      {disableOpen ? (
        <TotpDisableDialog t={t} onClose={() => setDisableOpen(false)} onStatus={onStatus} />
      ) : null}
    </div>
  );
}

function TotpBeginDialog({
  t,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  t: Translate;
  busy: boolean;
  error: string;
  onClose: () => void;
  onConfirm: (currentPassword: string) => Promise<void>;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
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
          <Button
            variant="primary"
            loading={busy}
            onClick={() => void onConfirm(currentPassword)}
            data-test-id="totp-begin-confirm"
          >
            {t("settings.twoFactor.confirmEnable")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field
          label={t("settings.twoFactor.currentPassword")}
          hint={t("settings.twoFactor.currentPasswordHint")}
        >
          <TextInput
            id="totp-begin-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.currentTarget.value)}
          />
        </Field>
        {error ? <StatusBanner live="alert" tone="signal" title={error} /> : null}
      </div>
    </Dialog>
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
  const submit = useTwoFactorSubmit();

  const confirm = async () => {
    await submit.run(async () => {
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/totp/confirm`, {
        method: "POST",
        body: { code: code.trim(), enrollment_nonce: setup.enrollment_nonce },
      });
      onStatus(next);
      onClose();
    }, genericMessage(t));
  };

  return (
    <Dialog
      title={t("settings.twoFactor.enableTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submit.busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="primary" loading={submit.busy} onClick={() => void confirm()} data-test-id="totp-confirm-btn">
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
        {submit.error ? <StatusBanner live="alert" tone="signal" title={submit.error} /> : null}
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
  const submit = useTwoFactorSubmit();

  const confirm = async () => {
    // BS-14: 停用第二因子需 step-up 重认证, 请求体附带 current_password。
    await submit.run(async () => {
      const next = await apiRequest<TwoFactorStatus>(`${BASE_URL}/totp/disable`, {
        method: "POST",
        body: { code: code.trim(), current_password: currentPassword },
      });
      onStatus(next);
      onClose();
    }, genericMessage(t));
  };

  return (
    <Dialog
      title={t("settings.twoFactor.disableTitle")}
      onClose={onClose}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submit.busy}>
            {t("settings.twoFactor.cancel")}
          </Button>
          <Button variant="danger" loading={submit.busy} onClick={() => void confirm()} data-test-id="totp-disable-confirm">
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
        {submit.error ? <StatusBanner live="alert" tone="signal" title={submit.error} /> : null}
      </div>
    </Dialog>
  );
}
