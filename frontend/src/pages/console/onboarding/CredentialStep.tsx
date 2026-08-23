import { KeyRound, Plus } from "lucide-react";

import { Button } from "../../../components/Button";
import { CodeBlock } from "../../../components/CodeBlock";
import { Field, TextInput } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import { StepFooter, StepPanel } from "./StepLayout";
import type { CredentialProgress } from "./types";
import { useCredentialStep } from "./useCredentialStep";

export function CredentialStep({
  appKey,
  activeCredentialCount,
  onProgressChange,
  onBack,
  onContinue,
}: {
  appKey: string;
  activeCredentialCount: number;
  onProgressChange: (progress: CredentialProgress | null) => void;
  onBack: () => void;
  onContinue: () => void;
}) {
  const { t } = useI18n();
  const credential = useCredentialStep(appKey, onProgressChange);
  const { credentialPending, continuationBlocked, secretEntries } = credential;

  return (
    <StepPanel title={t("wizard.credential.title")} description={t("wizard.credential.description")}>
      {activeCredentialCount > 0 ? (
        <StatusBanner tone="neutral" title={t("wizard.credential.existingCount", { count: activeCredentialCount })} />
      ) : null}
      <div className="grid max-w-3xl items-end gap-4 md:grid-cols-[minmax(0,1fr)_auto_auto]">
        <Field label={t("wizard.credential.name")}>
          <TextInput
            value={credential.name}
            disabled={credentialPending}
            onChange={(event) => credential.setName(event.currentTarget.value)}
            placeholder={t("wizard.credential.namePlaceholder")}
          />
        </Field>
        <Button
          variant="primary"
          icon={<Plus size={16} />}
          disabled={!credential.name || credentialPending}
          onClick={() => credential.createCredential("static-tokens")}
        >
          {t("wizard.credential.createStaticToken")}
        </Button>
        <Button
          icon={<KeyRound size={16} />}
          disabled={!credential.name || credentialPending}
          onClick={() => credential.createCredential("oauth-clients")}
        >
          {t("wizard.credential.createOauthClient")}
        </Button>
      </div>
      {credential.createError ? (
        <StatusBanner live="alert"
          tone="signal"
          title={t("wizard.credential.createFailed")}
          message={credential.createError.message}
        />
      ) : credential.exchangeError ? (
        <StatusBanner live="alert"
          tone="signal"
          title={t("wizard.credential.exchangeFailed")}
          message={credential.exchangeError.message}
        />
      ) : null}
      {secretEntries.length > 0 ? (
        <div className="space-y-3 rounded-[3px] border border-amber/30 bg-amber/8 p-4">
          <p className="text-sm font-semibold text-ink">{t("wizard.credential.secretTitle")}</p>
          <p className="text-body text-ink-soft">{t("wizard.credential.secretWarning")}</p>
          {secretEntries.map(([key, value]) => (
            <CodeBlock key={key} language={key} code={value} />
          ))}
        </div>
      ) : null}
      <p className="text-body text-ink-soft">{t("wizard.credential.skipHint")}</p>
      <StepFooter>
        <Button disabled={credentialPending} onClick={onBack}>{t("common.back")}</Button>
        <Button disabled={continuationBlocked} onClick={onContinue}>{t("common.skip")}</Button>
        <Button
          variant="primary"
          disabled={continuationBlocked || (secretEntries.length === 0 && activeCredentialCount === 0)}
          onClick={onContinue}
        >
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}
