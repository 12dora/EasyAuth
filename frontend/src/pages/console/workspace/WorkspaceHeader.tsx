import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { PageHeader } from "../../../components/PageHeader";
import { useI18n } from "../../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { AppSummary } from "../../../lib/domain";

export function WorkspaceHeader({
  appKey,
  app,
  onEditBasicInfo,
}: {
  appKey: string;
  app?: AppSummary;
  onEditBasicInfo: () => void;
}) {
  const { t } = useI18n();

  return (
    <PageHeader
      eyebrow={t("workspace.eyebrow")}
      title={app ? formatAppDisplayName(app) : appKey}
      description={app?.description || t("workspace.defaultDescription")}
      actions={
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <ButtonLink to="/console">{t("workspace.backToList")}</ButtonLink>
          {app?.capabilities?.can_edit_basic_info ? (
            <Button type="button" onClick={onEditBasicInfo}>
              {t("workspace.edit")}
            </Button>
          ) : null}
        </div>
      }
    />
  );
}
