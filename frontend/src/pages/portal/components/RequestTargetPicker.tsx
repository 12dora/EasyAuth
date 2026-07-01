import { Field, SelectInput } from "../../../components/Field";
import type { PortalCatalogApp } from "../../../lib/domain";
import type { AuthorizationGroupItem, ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/useAccessRequestForm";
import { PermissionSelector } from "./PermissionSelector";

interface RequestTargetPickerProps {
  appKey: string;
  authorizationGroupKey: string;
  apps: PortalCatalogApp[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  expandedGroupKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  onAppKeyChange: (appKey: string) => void;
  onAuthorizationGroupKeyChange: (groupKey: string) => void;
  onTogglePermission: (key: string) => void;
  onPermissionScopeChange: (permissionKey: string, scopeKey: string) => void;
  onToggleGroup: (key: string) => void;
}

export function RequestTargetPicker({
  appKey,
  authorizationGroupKey,
  apps,
  authorizationGroups,
  permissionGroups,
  ungroupedPermissions,
  selectedPermissionKeys,
  selectedPermissionScopes,
  expandedGroupKeys,
  catalogIsLoading,
  catalogErrorMessage,
  onAppKeyChange,
  onAuthorizationGroupKeyChange,
  onTogglePermission,
  onPermissionScopeChange,
  onToggleGroup,
}: RequestTargetPickerProps) {
  return (
    <>
      <Field label="应用" hint="来自员工门户可申请目录。">
        <SelectInput value={appKey} onChange={(event) => onAppKeyChange(event.currentTarget.value)}>
          <option value="">选择应用</option>
          {apps.map((app) => (
            <option key={app.app_key} value={app.app_key}>
              {app.name} ({app.app_key})
            </option>
          ))}
        </SelectInput>
      </Field>
      <Field label="可申请权限组" hint="展示 active、requestable 且有审批规则的 role 或 bundle。">
        <SelectInput
          value={authorizationGroupKey}
          onChange={(event) => onAuthorizationGroupKeyChange(event.currentTarget.value)}
          disabled={!appKey}
        >
          <option value="">不选择权限组</option>
          {authorizationGroups.map((group) => (
            <option key={`${group.app_key}:${group.key}`} value={group.key}>
              {group.name} [{group.kind}] ({group.key})
            </option>
          ))}
        </SelectInput>
      </Field>
      <div className="field">
        <span className="field-label">直接权限</span>
        <PermissionSelector
          appKey={appKey}
          groups={permissionGroups}
          ungroupedPermissions={ungroupedPermissions}
          selectedKeys={selectedPermissionKeys}
          selectedScopes={selectedPermissionScopes}
          expandedGroupKeys={expandedGroupKeys}
          loading={catalogIsLoading}
          errorMessage={catalogErrorMessage}
          onTogglePermission={onTogglePermission}
          onPermissionScopeChange={onPermissionScopeChange}
          onToggleGroup={onToggleGroup}
        />
        <span className="field-hint">
          {appKey ? `已选 ${selectedPermissionKeys.length} 项直接权限，可留空。` : "请先选择应用后再选择直接权限。"}
        </span>
      </div>
    </>
  );
}
