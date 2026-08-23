/** 权限选择器工具栏, 仅负责当前页批量操作入口。 */

import { useI18n } from "../../../i18n/I18nProvider";

import { PermissionSelectorScopeMenu } from "./PermissionSelectorScopeMenu";

export function PermissionSelectorToolbar({
  selectedCount,
  showSelectedOnly,
  onShowSelectedOnlyChange,
  onExpandAll,
  onCollapseAll,
  onSelectAll,
  onSelectScope,
  onClear,
}: {
  selectedCount: number;
  showSelectedOnly: boolean;
  onShowSelectedOnlyChange: (showSelectedOnly: boolean) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onSelectAll: () => void;
  onSelectScope: (scopeKey: string) => void;
  onClear: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="permission-selector__toolbar">
      <div className="permission-selector__toolbar-stats" aria-label={t("selector.toolbar.status")}>
        <span className="permission-selector__toolbar-stat">
          {t("selector.toolbar.selectedCount", { count: selectedCount })}
        </span>
        <label className="permission-selector__toolbar-toggle">
          <input
            type="checkbox"
            role="switch"
            aria-label={t("selector.toolbar.showSelectedOnly")}
            checked={showSelectedOnly}
            onChange={(event) => onShowSelectedOnlyChange(event.currentTarget.checked)}
          />
          <span aria-hidden="true" className="permission-selector__toolbar-toggle-track">
            <span className="permission-selector__toolbar-toggle-thumb" />
          </span>
          <span>{t("selector.toolbar.showSelectedOnly")}</span>
        </label>
      </div>
      <div className="permission-selector__toolbar-actions">
        <button type="button" className="permission-selector__toolbar-button" onClick={onExpandAll}>
          {t("selector.toolbar.expandAll")}
        </button>
        <button type="button" className="permission-selector__toolbar-button" onClick={onCollapseAll}>
          {t("selector.toolbar.collapseAll")}
        </button>
        <PermissionSelectorScopeMenu onSelectAll={onSelectAll} onSelectScope={onSelectScope} />
        <button type="button" className="permission-selector__toolbar-button" onClick={onClear}>
          {t("selector.toolbar.clear")}
        </button>
      </div>
    </div>
  );
}
