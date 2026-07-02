import { Field, SelectInput } from "../../../components/Field";
import type { PortalCatalogApp } from "../../../lib/domain";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/useAccessRequestForm";
import { PermissionSelector } from "./PermissionSelector";

interface RequestTargetPickerProps {
  appKey: string;
  apps: PortalCatalogApp[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  expandedGroupKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  onAppKeyChange: (appKey: string) => void;
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
  permissionGroups,
  ungroupedPermissions,
  selectedPermissionKeys,
  selectedPermissionScopes,
  expandedGroupKeys,
  catalogIsLoading,
  catalogErrorMessage,
  onAppKeyChange,
  onPermissionScopeChange,
  onPermissionGroupScopeChange,
  onSelectPermissionKeys,
  onClearPermissionKeys,
  onExpandGroups,
  onCollapseGroups,
  onToggleGroup,
}: RequestTargetPickerProps) {
  return (
    <>
      <Field label="应用">
        <SelectInput value={appKey} onChange={(event) => onAppKeyChange(event.currentTarget.value)}>
          <option value="">选择应用</option>
          {apps.map((app) => (
            <option key={app.app_key} value={app.app_key}>
              {app.name} ({app.app_key})
            </option>
          ))}
        </SelectInput>
      </Field>
      <Field
        label="直接权限"
        hint={appKey ? `已选 ${selectedPermissionKeys.length} 项权限范围，可留空。` : "请先选择应用后再选择直接权限。"}
      >
        <PermissionSelector
          appKey={appKey}
          groups={permissionGroups}
          ungroupedPermissions={ungroupedPermissions}
          selectedKeys={selectedPermissionKeys}
          selectedScopes={selectedPermissionScopes}
          expandedGroupKeys={expandedGroupKeys}
          loading={catalogIsLoading}
          errorMessage={catalogErrorMessage}
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
