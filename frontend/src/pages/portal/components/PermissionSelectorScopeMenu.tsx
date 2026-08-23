import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "../../../i18n/I18nProvider";
import type { MessageKey } from "../../../i18n/messages";

const SCOPE_SHORTCUTS: Array<{ scopeKey: string; labelKey: MessageKey }> = [
  { scopeKey: "SELF", labelKey: "selector.scope.self" },
  { scopeKey: "MANAGED_USERS", labelKey: "selector.scope.managedUsers" },
  { scopeKey: "ALL", labelKey: "selector.scope.all" },
];

/** 全选拆分按钮: 左半直接全选, 右半展开按范围全选的菜单。 */
export function PermissionSelectorScopeMenu({
  onSelectAll,
  onSelectScope,
}: {
  onSelectAll: () => void;
  onSelectScope: (scopeKey: string) => void;
}) {
  const { t } = useI18n();
  const [selectScopeMenuIsOpen, setSelectScopeMenuIsOpen] = useState(false);
  const selectScopeMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectScopeMenuIsOpen) {
      return;
    }

    function closeOnOutsidePointerDown(event: PointerEvent) {
      if (!selectScopeMenuRef.current?.contains(event.target as Node)) {
        setSelectScopeMenuIsOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectScopeMenuIsOpen(false);
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectScopeMenuIsOpen]);

  function selectScope(scopeKey: string) {
    onSelectScope(scopeKey);
    setSelectScopeMenuIsOpen(false);
  }

  return (
    <div ref={selectScopeMenuRef} className="permission-selector__toolbar-split-button">
      <button type="button" className="permission-selector__toolbar-button" onClick={onSelectAll}>
        {t("selector.toolbar.selectAll")}
      </button>
      <button
        type="button"
        className="permission-selector__toolbar-button"
        aria-label={t("selector.toolbar.selectScopeMenu")}
        aria-haspopup="menu"
        aria-expanded={selectScopeMenuIsOpen}
        onClick={() => setSelectScopeMenuIsOpen((isOpen) => !isOpen)}
      >
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {selectScopeMenuIsOpen ? (
        <div role="menu" className="permission-selector__toolbar-menu">
          {SCOPE_SHORTCUTS.map((shortcut) => (
            <button
              key={shortcut.scopeKey}
              type="button"
              role="menuitem"
              className="permission-selector__toolbar-menu-item"
              onClick={() => selectScope(shortcut.scopeKey)}
            >
              {t(shortcut.labelKey)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
