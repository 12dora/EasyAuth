import { Eye, FileUp, UploadCloud } from "lucide-react";
import { useRef } from "react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Field, TextArea } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { MessageKey } from "../../../i18n/messages";
import { StepFooter, StepPanel } from "./StepLayout";
import type { ManifestPreviewPayload } from "./types";
import { useCatalogStep } from "./useCatalogStep";
import { diffFromChanges } from "./wizardParsing";

export function CatalogStep({
  appKey,
  onBack,
  onContinue,
  onImportPendingChange,
}: {
  appKey: string;
  onBack: () => void;
  onContinue: () => void;
  onImportPendingChange: (pending: boolean) => void;
}) {
  const { t } = useI18n();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const catalog = useCatalogStep(appKey, onImportPendingChange);
  const { importPending } = catalog;

  return (
    <StepPanel title={t("wizard.catalog.title")} description={t("wizard.catalog.description")}>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.yaml,.yml,application/json,text/yaml,text/plain"
          className="sr-only"
          aria-label={t("wizard.catalog.uploadAria")}
          disabled={importPending}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) {
              catalog.selectFile(file);
            }
          }}
        />
        <Button disabled={importPending} icon={<FileUp size={16} />} onClick={() => fileInputRef.current?.click()}>
          {t("wizard.catalog.uploadFile")}
        </Button>
      </div>
      <Field label={t("wizard.catalog.content")} hint={t("wizard.catalog.contentHint")}>
        <TextArea
          aria-label={t("wizard.catalog.content")}
          rows={10}
          value={catalog.content}
          disabled={importPending}
          onChange={(event) => catalog.updateContent(event.currentTarget.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          icon={<Eye size={16} />}
          disabled={!catalog.content || catalog.previewPending || importPending}
          loading={catalog.previewPending}
          onClick={catalog.previewCurrentContent}
        >
          {t("wizard.catalog.preview")}
        </Button>
        <Button
          variant="primary"
          icon={<UploadCloud size={16} />}
          disabled={catalog.confirmDisabled}
          loading={importPending}
          onClick={catalog.importCurrentPreview}
        >
          {t("wizard.catalog.confirm")}
        </Button>
      </div>
      {catalog.previewError ? (
        <StatusBanner live="alert" tone="signal" title={t("wizard.catalog.previewFailed")} message={catalog.previewError.message} />
      ) : null}
      {catalog.importError ? (
        <StatusBanner live="alert" tone="signal" title={t("wizard.catalog.importFailed")} message={catalog.importError.message} />
      ) : null}
      {catalog.importedCatalogVersion ? (
        <StatusBanner
          live="status"
          tone="evergreen"
          title={t("wizard.catalog.importSuccess")}
          message={t("wizard.catalog.currentCatalogVersion", { version: catalog.importedCatalogVersion })}
        />
      ) : null}
      {catalog.currentPreview ? <ManifestDiffSummary preview={catalog.currentPreview} /> : null}
      <p className="text-body text-ink-soft">{t("wizard.catalog.skipHint")}</p>
      <StepFooter>
        <Button disabled={importPending} onClick={onBack}>{t("common.back")}</Button>
        <Button disabled={importPending} onClick={onContinue}>{t("common.skip")}</Button>
        <Button variant="primary" disabled={importPending || !catalog.importedCatalogVersion} onClick={onContinue}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function ManifestDiffSummary({ preview }: { preview: ManifestPreviewPayload }) {
  const { t } = useI18n();
  const diff = preview.diff ?? diffFromChanges(preview.changes ?? []);
  const sections = [
    { titleKey: "wizard.catalog.diff.added" as MessageKey, tone: "evergreen" as const, items: diff.added ?? [] },
    { titleKey: "wizard.catalog.diff.changed" as MessageKey, tone: "amber" as const, items: diff.changed ?? [] },
    { titleKey: "wizard.catalog.diff.removed" as MessageKey, tone: "signal" as const, items: diff.removed ?? [] },
  ];

  return (
    <div className="space-y-3">
      {sections.map((section) => (
        <div key={section.titleKey} className="rounded-[3px] border border-ink/10 bg-paper-soft p-3">
          <div className="mb-2 flex items-center gap-2">
            <Badge tone={section.tone}>{t(section.titleKey)}</Badge>
            <span className="text-body text-ink-soft">{section.items.length}</span>
          </div>
          {section.items.length > 0 ? (
            <ul className="grid gap-1 text-body text-ink-soft sm:grid-cols-2">
              {section.items.map((item, index) => (
                <li key={`${item.type ?? "item"}:${item.key ?? index}`}>
                  <code className="text-xs">{`${item.type ?? "-"}:${item.key ?? "-"}`}</code>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-body text-ink-soft">{t("wizard.catalog.diff.empty")}</p>
          )}
        </div>
      ))}
    </div>
  );
}
