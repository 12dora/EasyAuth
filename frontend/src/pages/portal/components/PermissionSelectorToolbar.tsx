/** 权限选择器工具栏, 仅负责当前页批量操作入口。 */

import { useI18n } from "../../../i18n/I18nProvider";

import { PermissionSelectorScopeMenu } from "./PermissionSelectorScopeMenu";

export function PermissionSelectorToolbar({
  selectedCount,
  showSelectedOnly,
  disabled,
  additionsDisabled,
  onShowSelectedOnlyChange,
  onExpandAll,
  onCollapseAll,
  onSelectAll,
  onSelectScope,
  onClear,
}: {
  selectedCount: number;
  showSelectedOnly: boolean;
  /** 目标整体只读(续期/提交中): 所有会改动目标的入口都要真正禁用, 否则点下去动作层直接抛错。 */
  disabled: boolean;
  /** 撤销申请: 目标只能往下减, 会往当前页加进基础授权之外权限的入口要禁用。 */
  additionsDisabled: boolean;
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
        {/* 只看已选与展开/折叠都只改视图, 不动申请目标: 目标只读时仍然可用, 否则连看都看不全。 */}
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
        <PermissionSelectorScopeMenu
          disabled={disabled || additionsDisabled}
          onSelectAll={onSelectAll}
          onSelectScope={onSelectScope}
        />
        {/* 清空是纯减法: 撤销申请允许清空(等于撤销全部), 只有目标整体只读时才禁用。 */}
        <button
          type="button"
          className="permission-selector__toolbar-button"
          disabled={disabled}
          onClick={onClear}
        >
          {t("selector.toolbar.clear")}
        </button>
      </div>
    </div>
  );
}
