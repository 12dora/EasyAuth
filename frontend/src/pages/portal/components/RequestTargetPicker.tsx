import { Select } from "antd";
import { useMemo } from "react";

import { Field, SelectInput } from "../../../components/Field";
import { useI18n, localizedField } from "../../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { PortalCatalogApp } from "../../../lib/domain";
import type { RevokeBaseGrantSnapshot } from "../hooks/accessRequestTargetLock";
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
  /**
   * 撤销申请的基础授权快照: 撤销目标是"撤销后保留下来的授权", 后端要求它是基础授权的真子集
   * (submission_validation._validate_revoke_subset), 所以基础授权之外的权限组与权限都不能勾。
   * null 表示不是撤销申请, 目标不受基础授权约束。
   */
  revokeBaseGrant?: RevokeBaseGrantSnapshot | null;
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
  revokeBaseGrant = null,
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
  const authorizationGroupOptions = useMemo(
    () =>
      authorizationGroups.map((group) => ({
        label: localizedField(locale, group.name, group.name_en),
        value: group.key,
        // 撤销时基础授权已有的组必须保持可选: 取消是撤销它, 再选回来是撤回这次撤销;
        // 基础授权之外的组加进来必被后端拒(submission_validation._validate_revoke_subset)。
        disabled: revokeBaseGrant !== null && !revokeBaseGrant.groupKeys.includes(group.key),
      })),
    [authorizationGroups, locale, revokeBaseGrant],
  );
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
        {/*
          一条授权可以同时挂多个权限组, 因此这里是多选: 单选控件会让变更申请静默撤掉没被选中的那些组。
          高度与圆角来自 APP_ANTD_THEME 的 controlHeight 36 / borderRadius 2, 与 SelectInput 的
          h-9 rounded-[2px] 是同一组设计令牌, 不需要额外样式。
        */}
        <Field
          label={t("portal.request.authorizationGroup")}
          hint={
            appKey
              ? t("portal.request.authorizationGroupsSelected", { count: authorizationGroupKeys.length })
              : t("portal.request.authorizationGroupNeedApp")
          }
        >
          <Select
            className="w-full"
            mode="multiple"
            value={authorizationGroupKeys}
            options={authorizationGroupOptions}
            placeholder={t("portal.request.authorizationGroupNone")}
            notFoundContent={t("portal.request.authorizationGroupEmpty")}
            allowClear
            maxTagCount="responsive"
            // 目录里的权限组可以有几十个, 保留 antd 多选默认的输入过滤; 但要按展示给用户的组名匹配,
            // antd 默认拿 value(也就是 group.key)去比, 用户看不到 key 就无从下手。
            optionFilterProp="label"
            // 应用未选定时目录里没有任何可申请权限组, 控件直接置灰; 选定应用后 authorizationGroups 变化, 选项随之出现。
            disabled={disabled || !appKey}
            onChange={onAuthorizationGroupKeysChange}
          />
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
          revokeBaseGrant={revokeBaseGrant}
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
