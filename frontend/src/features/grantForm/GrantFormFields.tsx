import { useMemo } from "react";

import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { useI18n } from "../../i18n/I18nProvider";
import { PermissionSelector } from "../../pages/portal/components/PermissionSelector";
import { keepLockedSelectionKeys } from "../../pages/portal/components/permissionSelectorRows";
import { descendantGroupKeys } from "../../pages/portal/hooks/accessRequestCatalog";
import {
  nextSelectionForGroupScopeClick,
  permissionScopeClickSelects,
} from "../../pages/portal/hooks/accessRequestScopeClick";
import { nextPermissionScopeSelection, uniqueStrings } from "../../pages/portal/hooks/accessRequestSelection";
import type {
  CatalogView,
  ScopedPermissionGroupItem,
  ScopedPermissionItem,
} from "../../pages/portal/hooks/accessRequestTypes";
import { grantDraftExpiresAtError, toDatetimeLocalValue } from "./grantDraft";
import type { GrantDraft, GrantTermType } from "./grantDraft";
import { grantDisplaySelectionKeys, grantDraftWithSelectionChange } from "./grantDraftSelection";

export function GrantPermissionField({
  appKey,
  catalogIsLoading,
  catalogErrorMessage,
  catalogView,
  coveredSelectionKeys,
  disabled,
  draft,
  expandedGroupKeys,
  lockedSelectionKeySet,
  lockedSelectionKeys,
  resolvedLockedHint,
  onDraftChange,
  setExpandedGroupKeys,
}: {
  appKey: string;
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  catalogView: CatalogView;
  coveredSelectionKeys: string[];
  disabled: boolean;
  draft: GrantDraft;
  expandedGroupKeys: string[];
  lockedSelectionKeySet: Set<string>;
  lockedSelectionKeys: string[];
  resolvedLockedHint: string;
  onDraftChange(next: GrantDraft): void;
  setExpandedGroupKeys: (updater: (current: string[]) => string[]) => void;
}) {
  const { t } = useI18n();
  const changeSelection = (change: (selectionKeys: string[]) => string[]) => {
    onDraftChange(
      grantDraftWithSelectionChange(draft, catalogView, (keys) =>
        change(keys).filter((key) => !lockedSelectionKeySet.has(key)),
      ),
    );
  };

  return (
    <Field as="group" label={t("grantForm.permissions")}>
      <PermissionSelector
        appKey={appKey}
        groups={catalogView.permissionGroups}
        ungroupedPermissions={catalogView.ungroupedPermissions}
        selectedKeys={draft.selectedPermissionKeys}
        coveredKeys={coveredSelectionKeys}
        lockedKeys={lockedSelectionKeys}
        lockedHint={resolvedLockedHint || undefined}
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
          changeSelection((current) =>
            keepLockedSelectionKeys(
              current,
              nextSelectionForGroupScopeClick(group, scopeKey, shouldSelect, current),
              lockedSelectionKeySet,
            ),
          );
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
  );
}

/** 收起一个权限分组时, 它的所有后代分组一起收起, 否则再展开会露出上次的深层展开态。 */
function collapseKeySet(keys: string[], permissionGroups: ScopedPermissionGroupItem[]): Set<string> {
  return new Set(keys.flatMap((key) => [key, ...descendantGroupKeys(permissionGroups, key)]));
}

export function GrantTermFields({
  disabled,
  draft,
  onDraftChange,
}: {
  disabled: boolean;
  draft: GrantDraft;
  onDraftChange(next: GrantDraft): void;
}) {
  const { t } = useI18n();
  const nowMin = useMemo(() => toDatetimeLocalValue(new Date()), []);
  const expiresAtError = grantDraftExpiresAtError(draft);
  return (
    <>
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
    </>
  );
}
