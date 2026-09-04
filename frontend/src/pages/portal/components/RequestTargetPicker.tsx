import { Field, SelectInput } from "../../../components/Field";
import { useI18n, localizedField } from "../../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { PortalCatalogApp } from "../../../lib/domain";
import type { AuthorizationGroupItem, ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { PermissionSelector } from "./PermissionSelector";

interface RequestTargetPickerProps {
  appKey: string;
  apps: PortalCatalogApp[];
  authorizationGroupKeys: string[];
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
  onAuthorizationGroupKeysChange: (groupKeys: string[]) => void;
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
  authorizationGroupKeys,
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
  onAuthorizationGroupKeysChange,
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
                {formatAppDisplayName(app)}
              </option>
            ))}
          </SelectInput>
        </Field>
      </div>
      {/* 一条授权可以同时挂多个权限组, 因此这里是多选: 单选控件会让变更申请静默撤掉没被选中的那些组。 */}
      <Field
        as="group"
        label={t("portal.request.authorizationGroup")}
        hint={
          appKey
            ? t("portal.request.authorizationGroupsSelected", { count: authorizationGroupKeys.length })
            : t("portal.request.authorizationGroupNeedApp")
        }
      >
        <div className="max-h-40 overflow-auto rounded-[2px] border border-ink/15 bg-paper-soft p-2">
          {authorizationGroups.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {authorizationGroups.map((group) => (
                <label
                  key={`${group.app_key}:${group.key}`}
                  className="inline-flex items-center gap-2 rounded-[2px] px-2 py-1.5 text-body text-ink-soft hover:bg-ink/5"
                >
                  <input
                    type="checkbox"
                    value={group.key}
                    checked={authorizationGroupKeys.includes(group.key)}
                    disabled={disabled || !appKey}
                    onChange={(event) =>
                      onAuthorizationGroupKeysChange(
                        event.currentTarget.checked
                          ? [...authorizationGroupKeys, group.key]
                          : authorizationGroupKeys.filter((key) => key !== group.key),
                      )
                    }
                  />
                  <span className="text-ink">{localizedField(locale, group.name, group.name_en)}</span>
                </label>
              ))}
            </div>
          ) : (
            <span className="block px-2 py-1.5 text-body text-ink-faint">
              {appKey ? t("portal.request.authorizationGroupEmpty") : t("portal.request.authorizationGroupNeedApp")}
            </span>
          )}
        </div>
      </Field>
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
