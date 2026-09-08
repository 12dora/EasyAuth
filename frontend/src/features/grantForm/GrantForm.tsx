import { Select } from "antd";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { localizedField, useI18n } from "../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { PermissionSelector } from "../../pages/portal/components/PermissionSelector";
import {
  buildCatalogView,
  descendantGroupKeys,
  groupCoveredSelectionKeys,
} from "../../pages/portal/hooks/accessRequestCatalog";
import {
  nextSelectionForGroupScopeClick,
  permissionScopeClickSelects,
} from "../../pages/portal/hooks/accessRequestScopeClick";
import { nextPermissionScopeSelection, uniqueStrings } from "../../pages/portal/hooks/accessRequestSelection";
import type {
  PortalRequestCatalogView,
  ScopedPermissionGroupItem,
  ScopedPermissionItem,
} from "../../pages/portal/hooks/accessRequestTypes";
import { grantDraftExpiresAtError, toDatetimeLocalValue } from "./grantDraft";
import type { GrantDraft, GrantTermType } from "./grantDraft";
import {
  grantDisplaySelectionKeys,
  grantDraftWithAppKey,
  grantDraftWithAuthorizationGroupKeys,
  grantDraftWithSelectionChange,
} from "./grantDraftSelection";

export interface GrantFormProps {
  catalog: PortalRequestCatalogView | undefined;
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  draft: GrantDraft;
  onDraftChange(next: GrantDraft): void;
  disabled?: boolean;
  /** 编辑既有策略时应用不可改(后端拒绝跨应用改写), 应用选择器固定并置灰。 */
  lockedAppKey?: string;
  /** 渲染在目标选择器上方的插槽(直接授权页放"被授权人")。 */
  header?: ReactNode;
}

/**
 * 授权表单: 应用 → 授权组 + 权限树 → 有效期 → 说明。
 *
 * 只持有展开态这一份界面状态, 草稿完全由调用方持有, 因此同一个组件既能服务"授予权限"页,
 * 也能服务组织授权策略的新建/编辑弹窗。
 */
export function GrantForm({
  catalog,
  catalogIsLoading,
  catalogErrorMessage,
  draft,
  onDraftChange,
  disabled = false,
  lockedAppKey,
  header,
}: GrantFormProps) {
  const { t, locale } = useI18n();
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const appKey = lockedAppKey ?? draft.appKey;
  // 目录视图与门户申请共用同一条路径; 控制台没有"排除自己"的审批人语义, currentUserId 传空串。
  const catalogView = useMemo(() => buildCatalogView(catalog, appKey, ""), [catalog, appKey]);
  const coveredSelectionKeys = useMemo(
    () => groupCoveredSelectionKeys(draft.authorizationGroupKeys, catalogView),
    [draft.authorizationGroupKeys, catalogView],
  );
  const nowMin = useMemo(() => toDatetimeLocalValue(new Date()), []);
  const expiresAtError = grantDraftExpiresAtError(draft);

  const authorizationGroupOptions = useMemo(
    () =>
      catalogView.authorizationGroups.map((group) => ({
        label: localizedField(locale, group.name, group.name_en),
        value: group.key,
      })),
    [catalogView.authorizationGroups, locale],
  );

  const changeSelection = (change: (selectionKeys: string[]) => string[]) => {
    onDraftChange(grantDraftWithSelectionChange(draft, catalogView, change));
  };

  return (
    <div className="flex flex-col gap-5">
      {header}
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("grantForm.app")}>
          <SelectInput
            value={appKey}
            disabled={disabled || Boolean(lockedAppKey)}
            onChange={(event) => {
              setExpandedGroupKeys([]);
              onDraftChange(grantDraftWithAppKey(draft, event.currentTarget.value));
            }}
          >
            <option value="">{t("grantForm.appPlaceholder")}</option>
            {(catalog?.apps ?? []).map((app) => (
              <option key={app.app_key} value={app.app_key}>
                {formatAppDisplayName(app)}
              </option>
            ))}
          </SelectInput>
        </Field>
        {/*
          一条授权可以同时挂多个授权组, 因此这里是多选。高度与圆角来自 APP_ANTD_THEME 的
          controlHeight 36 / borderRadius 2, 与 SelectInput 的 h-9 rounded-[2px] 是同一组设计令牌。
        */}
        <Field label={t("grantForm.authorizationGroup")}>
          <Select
            className="w-full"
            mode="multiple"
            value={draft.authorizationGroupKeys}
            options={authorizationGroupOptions}
            placeholder={t("grantForm.authorizationGroupNone")}
            notFoundContent={t("grantForm.authorizationGroupEmpty")}
            allowClear
            maxTagCount="responsive"
            // 目录里的授权组可以有几十个, 按展示给用户的组名过滤; antd 默认拿 value(group.key)比对,
            // 用户看不到 key 就无从下手。
            optionFilterProp="label"
            disabled={disabled || !appKey}
            onChange={(groupKeys: string[]) =>
              onDraftChange(grantDraftWithAuthorizationGroupKeys(draft, groupKeys, catalogView))
            }
          />
        </Field>
      </div>
      <Field as="group" label={t("grantForm.permissions")}>
        <PermissionSelector
          appKey={appKey}
          groups={catalogView.permissionGroups}
          ungroupedPermissions={catalogView.ungroupedPermissions}
          selectedKeys={draft.selectedPermissionKeys}
          coveredKeys={coveredSelectionKeys}
          revokeBaseGrant={null}
          expandedGroupKeys={expandedGroupKeys}
          loading={catalogIsLoading}
          errorMessage={catalogErrorMessage}
          disabled={disabled}
          onPermissionScopeChange={(permission: ScopedPermissionItem, scopeKey: string) => {
            // 勾选态看的是展示态: 授权组覆盖的权限也画成勾选, 再点一次就是"取消"。方向只按展示态定一次,
            // 后面对直接权限集合重放同一次变更时不能再算一遍, 否则被覆盖的项会反向变成"选中"。
            const shouldSelect = permissionScopeClickSelects(
              permission,
              scopeKey,
              grantDisplaySelectionKeys(draft, catalogView),
            );
            changeSelection((current) => nextPermissionScopeSelection(permission, scopeKey, shouldSelect, current));
          }}
          onPermissionGroupScopeChange={(group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => {
            if (!scopeKey) {
              return;
            }
            changeSelection((current) => nextSelectionForGroupScopeClick(group, scopeKey, shouldSelect, current));
          }}
          onSelectPermissionKeys={(keys: string[]) => {
            changeSelection((current) => uniqueStrings([...current, ...keys]));
          }}
          onClearPermissionKeys={(keys: string[]) => {
            const keySet = new Set(keys);
            changeSelection((current) => current.filter((key) => !keySet.has(key)));
          }}
          onExpandGroups={(keys: string[]) => setExpandedGroupKeys((current) => uniqueStrings([...current, ...keys]))}
          onCollapseGroups={(keys: string[]) => {
            const keySet = collapseKeySet(keys, catalogView.permissionGroups);
            setExpandedGroupKeys((current) => current.filter((key) => !keySet.has(key)));
          }}
          onToggleGroup={(key: string) =>
            setExpandedGroupKeys((current) => {
              if (!current.includes(key)) {
                return [...current, key];
              }
              const keySet = collapseKeySet([key], catalogView.permissionGroups);
              return current.filter((item) => !keySet.has(item));
            })
          }
        />
      </Field>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("grantForm.term")}>
          <SelectInput
            value={draft.grantType}
            disabled={disabled}
            onChange={(event) => {
              const grantType = event.currentTarget.value as GrantTermType;
              // 切回长期必须同时清掉到期时间与它的回填来源, 否则草稿会带着不会被提交的残值。
              onDraftChange(
                grantType === "timed"
                  ? { ...draft, grantType }
                  : { ...draft, grantType, expiresAt: "", expiresAtSource: "" },
              );
            }}
          >
            <option value="permanent">{t("grantForm.term.permanent")}</option>
            <option value="timed">{t("grantForm.term.timed")}</option>
          </SelectInput>
        </Field>
        <Field
          label={t("grantForm.expiresAt")}
          error={expiresAtError ? t("grantForm.expiresAtInvalid") : undefined}
        >
          <TextInput
            type="datetime-local"
            value={draft.expiresAt}
            min={nowMin}
            disabled={disabled || draft.grantType !== "timed"}
            // 用户一动控件, 回填来源(带秒/微秒的原始时间戳)立即作废, 以控件值为准。
            onChange={(event) =>
              onDraftChange({ ...draft, expiresAt: event.currentTarget.value, expiresAtSource: "" })
            }
          />
        </Field>
      </div>
      <Field label={t("grantForm.reason")}>
        <TextArea
          rows={4}
          value={draft.reason}
          disabled={disabled}
          placeholder={t("grantForm.reasonPlaceholder")}
          onChange={(event) => onDraftChange({ ...draft, reason: event.currentTarget.value })}
        />
      </Field>
    </div>
  );
}

/** 收起一个权限分组时, 它的所有后代分组一起收起, 否则再展开会露出上次的深层展开态。 */
function collapseKeySet(keys: string[], permissionGroups: ScopedPermissionGroupItem[]): Set<string> {
  return new Set(keys.flatMap((key) => [key, ...descendantGroupKeys(permissionGroups, key)]));
}
