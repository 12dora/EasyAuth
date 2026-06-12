import { Field, SelectInput } from "../../../components/Field";
import type { PermissionGroupItem, PermissionItem, PortalCatalogApp, PortalCatalogRole } from "../../../lib/domain";
import { PermissionSelector } from "./PermissionSelector";

interface RequestTargetPickerProps {
  appKey: string;
  roleKey: string;
  apps: PortalCatalogApp[];
  roles: PortalCatalogRole[];
  permissionGroups: PermissionGroupItem[];
  ungroupedPermissions: PermissionItem[];
  selectedPermissionKeys: string[];
  expandedGroupKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  onAppKeyChange: (appKey: string) => void;
  onRoleKeyChange: (roleKey: string) => void;
  onTogglePermission: (key: string) => void;
  onToggleGroup: (key: string) => void;
}

export function RequestTargetPicker({
  appKey,
  roleKey,
  apps,
  roles,
  permissionGroups,
  ungroupedPermissions,
  selectedPermissionKeys,
  expandedGroupKeys,
  catalogIsLoading,
  catalogErrorMessage,
  onAppKeyChange,
  onRoleKeyChange,
  onTogglePermission,
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
      <Field label="角色" hint="仅展示 active、requestable 且有审批规则的角色。">
        <SelectInput value={roleKey} onChange={(event) => onRoleKeyChange(event.currentTarget.value)} disabled={!appKey}>
          <option value="">不选择角色</option>
          {roles.map((role) => (
            <option key={`${role.app_key}:${role.key}`} value={role.key}>
              {role.name} ({role.key})
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
          expandedGroupKeys={expandedGroupKeys}
          loading={catalogIsLoading}
          errorMessage={catalogErrorMessage}
          onTogglePermission={onTogglePermission}
          onToggleGroup={onToggleGroup}
        />
        <span className="field-hint">
          {appKey ? `已选 ${selectedPermissionKeys.length} 项直接权限，可留空。` : "请先选择应用后再选择直接权限。"}
        </span>
      </div>
    </>
  );
}
