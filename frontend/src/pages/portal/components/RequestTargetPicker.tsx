import { Field, SelectInput } from "../../../components/Field";
import { useI18n, localizedField } from "../../../i18n/I18nProvider";
import type { PortalCatalogApp } from "../../../lib/domain";
import type { AuthorizationGroupItem, ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/useAccessRequestForm";
import { PermissionSelector } from "./PermissionSelector";

interface RequestTargetPickerProps {
  appKey: string;
  apps: PortalCatalogApp[];
  authorizationGroupKey: string;
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  selectedPermissionKeys: string[];
  coveredSelectionKeys?: string[];
  expandedGroupKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  disabled?: boolean;
  onAppKeyChange: (appKey: string) => void;
  onAuthorizationGroupKeyChange: (groupKey: string) => void;
  onPermissionScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
  onPermissionGroupScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  onSelectPermissionKeys: (selectionKeys: string[]) => void;
  onClearPermissionKeys: (selectionKeys: string[]) => void;
  onExpandGroups: (groupKeys: string[]) => void;
  onCollapseGroups: (groupKeys: string[]) => void;
  onToggleGroup: (key: string) => void;
}

export function RequestTargetPicker({
  appKey,
  apps,
  authorizationGroupKey,
  authorizationGroups,
  permissionGroups,
  ungroupedPermissions,
  selectedPermissionKeys,
  coveredSelectionKeys = [],
  expandedGroupKeys,
  catalogIsLoading,
  catalogErrorMessage,
  disabled = false,
  onAppKeyChange,
  onAuthorizationGroupKeyChange,
  onPermissionScopeChange,
  onPermissionGroupScopeChange,
  onSelectPermissionKeys,
  onClearPermissionKeys,
  onExpandGroups,
  onCollapseGroups,
  onToggleGroup,
}: RequestTargetPickerProps) {
  const { t, locale } = useI18n();
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("portal.request.app")}>
          <SelectInput
            value={appKey}
            disabled={disabled}
            onChange={(event) => onAppKeyChange(event.currentTarget.value)}
          >
            <option value="">{t("portal.request.appPlaceholder")}</option>
            {apps.map((app) => (
              <option key={app.app_key} value={app.app_key}>
                {app.name} ({app.app_key})
              </option>
            ))}
          </SelectInput>
        </Field>
        <Field label={t("portal.request.authorizationGroup")}>
          <SelectInput
            value={authorizationGroupKey}
            onChange={(event) => onAuthorizationGroupKeyChange(event.currentTarget.value)}
            disabled={disabled || !appKey}
          >
            <option value="">{t("portal.request.authorizationGroupNone")}</option>
            {authorizationGroups.map((group) => (
              <option key={`${group.app_key}:${group.key}`} value={group.key}>
                {localizedField(locale, group.name, group.name_en)} [{group.kind}] ({group.key})
              </option>
            ))}
          </SelectInput>
        </Field>
      </div>
      <Field
        as="group"
        label={t("portal.request.directPermissions")}
        hint={
          appKey
            ? t("portal.request.directPermissionsSelected", { count: selectedPermissionKeys.length })
            : t("portal.request.directPermissionsNeedApp")
        }
      >
        <PermissionSelector
          appKey={appKey}
          groups={permissionGroups}
          ungroupedPermissions={ungroupedPermissions}
          selectedKeys={selectedPermissionKeys}
          coveredKeys={coveredSelectionKeys}
          expandedGroupKeys={expandedGroupKeys}
          loading={catalogIsLoading}
          errorMessage={catalogErrorMessage}
          disabled={disabled}
          onPermissionScopeChange={onPermissionScopeChange}
          onPermissionGroupScopeChange={onPermissionGroupScopeChange}
          onSelectPermissionKeys={onSelectPermissionKeys}
          onClearPermissionKeys={onClearPermissionKeys}
          onExpandGroups={onExpandGroups}
          onCollapseGroups={onCollapseGroups}
          onToggleGroup={onToggleGroup}
        />
      </Field>
    </>
  );
}
