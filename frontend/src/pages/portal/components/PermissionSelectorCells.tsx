import { ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";
import { useEffect, useRef } from "react";

import { cn } from "../../../lib/cn";
import { localizedName, useI18n } from "../../../i18n/I18nProvider";
import type { Locale } from "../../../i18n/messages";

import { directGrantSelectionKey } from "../hooks/accessRequestSelection";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { groupScopeSelectionState, type ScopeOptionView } from "./permissionSelectorRows";

export function PermissionGroupNameCell({
  group,
  depth,
  isExpanded,
  selectedCount,
  permissionCount,
  onToggleGroup,
  locale,
}: {
  group: ScopedPermissionGroupItem;
  depth: number;
  isExpanded: boolean;
  selectedCount: number;
  permissionCount: number;
  onToggleGroup: (key: string) => void;
  locale: Locale;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      className="permission-selector__group-button"
      onClick={(event) => {
        event.stopPropagation();
        onToggleGroup(group.key);
      }}
      aria-expanded={isExpanded}
      aria-label={`${isExpanded ? t("selector.group.collapse") : t("selector.group.expand")} ${localizedName(locale, group)}`}
      style={depthStyle(depth)}
    >
      <span className="permission-selector__tree-rail" aria-hidden="true" />
      <ChevronRight size={16} className={isExpanded ? "permission-selector__chevron permission-selector__chevron--expanded" : "permission-selector__chevron"} />
      <span className="permission-selector__group-name">{localizedName(locale, group)}</span>
      <span className={selectedCount > 0 ? "permission-selector__group-count permission-selector__group-count--active" : "permission-selector__group-count"}>
        {selectedCount}/{permissionCount}
      </span>
    </button>
  );
}

export function PermissionNameCell({
  permission,
  depth,
  locale,
}: {
  permission: ScopedPermissionItem;
  depth: number;
  locale: Locale;
}) {
  return (
    <span className="permission-selector__permission-name" style={depthStyle(depth)}>
      <span className="permission-selector__leaf-marker" aria-hidden="true" />
      <span className="permission-selector__permission-label">{localizedName(locale, permission)}</span>
    </span>
  );
}

export function PermissionGroupScopeCell({
  group,
  scopeOptions,
  selectedKeys,
  onScopeChange,
  locale,
}: {
  group: ScopedPermissionGroupItem;
  scopeOptions: ScopeOptionView[];
  selectedKeys: string[];
  onScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  locale: Locale;
}) {
  const { t } = useI18n();
  if (scopeOptions.length === 0) {
    return <span aria-label={t("selector.group.noScope")}>-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopeOptions.map((scope) => {
        const selectionState = groupScopeSelectionState(group, scope.key, selectedKeys);

        return (
          <ScopeChip
            key={scope.key}
            label={localizedName(locale, scope)}
            checked={selectionState === "checked"}
            mixed={selectionState === "indeterminate"}
            ariaLabel={t("selector.selectGroupScope", { groupKey: group.key, scopeName: localizedName(locale, scope) })}
            // 全勾时点一下清空整个范围; 未勾与半勾都补齐成全勾, 半勾不再变成"再点一次也没反应"。
            onChange={() => onScopeChange(group, scope.key, selectionState !== "checked")}
          />
        );
      })}
    </div>
  );
}

export function PermissionScopeCell({
  permission,
  selectedKeys,
  coveredKeySet,
  onScopeChange,
  locale,
}: {
  permission: ScopedPermissionItem;
  selectedKeys: string[];
  coveredKeySet?: Set<string>;
  onScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
  locale: Locale;
}) {
  const { t } = useI18n();
  const scopes = permission.scopes ?? [];
  if (scopes.length === 0) {
    return <span aria-label={t("selector.permission.noScope", { permissionKey: permission.key })}>-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopes.map((scope) => {
        const selectionKey = directGrantSelectionKey(permission.key, scope.key);
        // 权限组覆盖的权限同样可编辑: 取消勾选会把权限组落地成逐项直接申请(见 accessRequestActions)。
        const isCovered = coveredKeySet?.has(selectionKey) ?? false;
        const scopeLabel = t("selector.selectPermissionScope", { permissionKey: permission.key, scopeName: localizedName(locale, scope) });
        return (
          <ScopeChip
            key={scope.key}
            label={localizedName(locale, scope)}
            checked={selectedKeys.includes(selectionKey)}
            covered={isCovered}
            title={isCovered ? t("selector.scope.coveredByGroup") : undefined}
            ariaLabel={scopeLabel}
            onChange={() => onScopeChange(permission, scope.key)}
          />
        );
      })}
    </div>
  );
}

function ScopeChip({
  label,
  checked,
  mixed = false,
  covered = false,
  title,
  ariaLabel,
  onChange,
}: {
  label: string;
  checked: boolean;
  mixed?: boolean;
  /** 由所选权限组带来的权限范围: 与直接勾选同样可点, 只在样式上标出来源。 */
  covered?: boolean;
  title?: string;
  ariaLabel: string;
  onChange: () => void;
}) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = mixed;
    }
  }, [mixed]);

  return (
    <label
      title={title}
      className={cn(
        "permission-selector__scope-chip",
        checked && "permission-selector__scope-chip--checked",
        mixed && "permission-selector__scope-chip--mixed",
        covered && "permission-selector__scope-chip--covered",
      )}
    >
      <input
        ref={checkboxRef}
        type="checkbox"
        checked={checked}
        aria-checked={mixed ? "mixed" : checked}
        onChange={onChange}
        aria-label={ariaLabel}
      />
      <span>{label}</span>
    </label>
  );
}

function depthStyle(depth: number): CSSProperties {
  return { "--permission-depth": depth } as CSSProperties;
}
