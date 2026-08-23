import { SelectInput } from "../../components/Field";
import { useI18n } from "../../i18n/I18nProvider";
import type { HandoverAssetAction } from "../../lib/domain";

export function AssetActionSelect({
  value,
  releasable,
  disabled,
  onChange,
  "aria-label": ariaLabel,
}: {
  value: HandoverAssetAction;
  releasable: boolean;
  disabled?: boolean;
  onChange: (value: HandoverAssetAction) => void;
  "aria-label"?: string;
}) {
  const { t } = useI18n();
  return (
    <SelectInput
      className="w-40"
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      title={!releasable ? t("handover.allocator.releaseDisabled") : undefined}
      onChange={(event) => onChange(event.currentTarget.value as HandoverAssetAction)}
    >
      <option value="transfer">{t("handover.allocator.action.transfer")}</option>
      <option value="release" disabled={!releasable}>
        {t("handover.allocator.action.release")}
      </option>
      <option value="skip">{t("handover.allocator.action.skip")}</option>
    </SelectInput>
  );
}
