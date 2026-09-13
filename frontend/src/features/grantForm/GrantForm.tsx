import { Select } from "antd";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Field, SelectInput } from "../../components/Field";
import { localizedField, useI18n } from "../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import {
  buildCatalogView,
  groupCoveredSelectionKeys,
} from "../../pages/portal/hooks/accessRequestCatalog";
import { uniqueStrings } from "../../pages/portal/hooks/accessRequestSelection";
import type { CatalogView, PortalRequestCatalogView } from "../../pages/portal/hooks/accessRequestTypes";
import type { GrantDraft } from "./grantDraft";
import { GrantPermissionField, GrantTermFields } from "./GrantFormFields";
import { LockedSelectTag, requireGrantLockedHint, wrapLockedSelectContent } from "./grantFormLocked";
import { grantDraftWithAppKey, grantDraftWithAuthorizationGroupKeys } from "./grantDraftSelection";

const EMPTY_KEYS: string[] = [];

export interface GrantFormProps {
  catalog: PortalRequestCatalogView | undefined;
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  draft: GrantDraft;
  onDraftChange(next: GrantDraft): void;
  disabled?: boolean;
  /** 编辑既有策略时应用不可改(后端拒绝跨应用改写), 应用选择器固定并置灰。 */
  lockedAppKey?: string;
  /**
   * 组织授权下发的授权组: 展示为不可移除的选中标签, 不进草稿。
   * 缺省空数组, 组织授权策略编辑不传。
   */
  lockedAuthorizationGroupKeys?: string[];
  /**
   * 组织授权下发的直接权限选择键; 与锁定组覆盖的范围一并交给 PermissionSelector.lockedKeys。
   */
  lockedPermissionKeys?: string[];
  /**
   * 锁定项的悬停说明。有锁定组或锁定权限时必填。
   */
  lockedHint?: string;
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
  lockedAuthorizationGroupKeys = EMPTY_KEYS,
  lockedPermissionKeys = EMPTY_KEYS,
  lockedHint,
  header,
}: GrantFormProps) {
  const { t, locale } = useI18n();
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const appKey = lockedAppKey ?? draft.appKey;
  // 目录视图与门户申请共用同一条路径; 控制台没有"排除自己"的审批人语义, currentUserId 传空串。
  const catalogView = useMemo(() => buildCatalogView(catalog, appKey, ""), [catalog, appKey]);
  const lockedGroupKeySet = useMemo(() => new Set(lockedAuthorizationGroupKeys), [lockedAuthorizationGroupKeys]);
  const lockedSelectionKeys = useMemo(
    () =>
      uniqueStrings([
        ...lockedPermissionKeys,
        ...groupCoveredSelectionKeys(lockedAuthorizationGroupKeys, catalogView),
      ]),
    [catalogView, lockedAuthorizationGroupKeys, lockedPermissionKeys],
  );
  const lockedSelectionKeySet = useMemo(() => new Set(lockedSelectionKeys), [lockedSelectionKeys]);
  const resolvedLockedHint = requireGrantLockedHint(
    lockedAuthorizationGroupKeys,
    lockedSelectionKeys,
    lockedHint,
  );
  const coveredSelectionKeys = useMemo(
    () => groupCoveredSelectionKeys(draft.authorizationGroupKeys, catalogView),
    [draft.authorizationGroupKeys, catalogView],
  );
  // 锁定组始终出现在选中值里(antd 对 disabled option 的 tag 不渲染关闭按钮), 草稿本身只有本人可改的组。
  const displayedAuthorizationGroupKeys = useMemo(
    () => uniqueStrings([...lockedAuthorizationGroupKeys, ...draft.authorizationGroupKeys]),
    [draft.authorizationGroupKeys, lockedAuthorizationGroupKeys],
  );

  const authorizationGroupOptions = useMemo(() => {
    const fromCatalog = catalogView.authorizationGroups.map((group) => ({
      label: localizedField(locale, group.name, group.name_en),
      value: group.key,
      disabled: lockedGroupKeySet.has(group.key),
    }));
    const knownKeys = new Set(fromCatalog.map((option) => option.value));
    const extras = lockedAuthorizationGroupKeys
      .filter((key) => !knownKeys.has(key))
      .map((key) => ({ label: key, value: key, disabled: true }));
    return [...fromCatalog, ...extras];
  }, [catalogView.authorizationGroups, locale, lockedAuthorizationGroupKeys, lockedGroupKeySet]);

  return (
    <div className="flex flex-col gap-5">
      {header}
      <GrantAppAndGroupFields
        appKey={appKey}
        authorizationGroupOptions={authorizationGroupOptions}
        catalog={catalog}
        catalogView={catalogView}
        disabled={disabled}
        displayedAuthorizationGroupKeys={displayedAuthorizationGroupKeys}
        draft={draft}
        lockedAppKey={lockedAppKey}
        lockedGroupKeySet={lockedGroupKeySet}
        resolvedLockedHint={resolvedLockedHint}
        onDraftChange={onDraftChange}
        setExpandedGroupKeys={setExpandedGroupKeys}
      />
      <GrantPermissionField
        appKey={appKey}
        catalogErrorMessage={catalogErrorMessage}
        catalogIsLoading={catalogIsLoading}
        catalogView={catalogView}
        coveredSelectionKeys={coveredSelectionKeys}
        disabled={disabled}
        draft={draft}
        expandedGroupKeys={expandedGroupKeys}
        lockedSelectionKeySet={lockedSelectionKeySet}
        lockedSelectionKeys={lockedSelectionKeys}
        resolvedLockedHint={resolvedLockedHint}
        onDraftChange={onDraftChange}
        setExpandedGroupKeys={setExpandedGroupKeys}
      />
      <GrantTermFields disabled={disabled} draft={draft} onDraftChange={onDraftChange} />
    </div>
  );
}

function GrantAppAndGroupFields({
  appKey,
  authorizationGroupOptions,
  catalog,
  catalogView,
  disabled,
  displayedAuthorizationGroupKeys,
  draft,
  lockedAppKey,
  lockedGroupKeySet,
  resolvedLockedHint,
  onDraftChange,
  setExpandedGroupKeys,
}: {
  appKey: string;
  authorizationGroupOptions: Array<{ label: string; value: string; disabled: boolean }>;
  catalog: PortalRequestCatalogView | undefined;
  catalogView: CatalogView;
  disabled: boolean;
  displayedAuthorizationGroupKeys: string[];
  draft: GrantDraft;
  lockedAppKey?: string;
  lockedGroupKeySet: Set<string>;
  resolvedLockedHint: string;
  onDraftChange(next: GrantDraft): void;
  setExpandedGroupKeys: (updater: (current: string[]) => string[]) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label={t("grantForm.app")}>
        <SelectInput
          value={appKey}
          disabled={disabled || Boolean(lockedAppKey)}
          onChange={(event) => {
            setExpandedGroupKeys(() => []);
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
          value={displayedAuthorizationGroupKeys}
          options={authorizationGroupOptions}
          placeholder={t("grantForm.authorizationGroupNone")}
          notFoundContent={t("grantForm.authorizationGroupEmpty")}
          allowClear
          maxTagCount="responsive"
          // 目录里的授权组可以有几十个, 按展示给用户的组名过滤; antd 默认拿 value(group.key)比对,
          // 用户看不到 key 就无从下手。
          optionFilterProp="label"
          disabled={disabled || !appKey}
          optionRender={(option) =>
            wrapLockedSelectContent(String(option.value), option.label, lockedGroupKeySet, resolvedLockedHint)
          }
          tagRender={(props) => (
            <LockedSelectTag
              label={props.label}
              value={String(props.value)}
              closable={props.closable && !lockedGroupKeySet.has(String(props.value))}
              onClose={props.onClose}
              lockedGroupKeySet={lockedGroupKeySet}
              lockedHint={resolvedLockedHint}
            />
          )}
          onChange={(groupKeys: string[]) =>
            onDraftChange(
              grantDraftWithAuthorizationGroupKeys(
                draft,
                // allowClear / 关 tag 都可能把锁定组带下来; 从交给草稿的值里剥掉, 展示值再拼回去。
                groupKeys.filter((key) => !lockedGroupKeySet.has(key)),
                catalogView,
              ),
            )
          }
        />
      </Field>
    </div>
  );
}
