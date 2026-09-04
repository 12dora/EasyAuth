/**
 * 「我的权限」表格的权限详情单元格: 表格里只显示条数, 悬停或聚焦时用浮层逐条列出。
 *
 * 一条授权展开后动辄几十项权限, 原来把它们拼成一串塞进单元格, 行高被撑到几十行、
 * 整张表没法看; 条数 + 浮层既保住了「我到底有多少权限」这个第一眼信息,
 * 又让明细随时可查。浮层按来源分组(角色的权限归在角色名下, 直接授权单列一组),
 * 因为员工要回答的往往是「这项权限是哪个角色带来的」。
 *
 * 浮层交给 antd Popover: 手写的版本把浮层挂在 body 上, 指针刚离开触发器就 onMouseLeave 关掉,
 * 于是长列表的滚动条永远够不着, 贴到视口底部也不会翻转。Popover 在浮层自身上挂了
 * mouseenter/mouseleave 并带关闭延时, 指针能安全走进去, 位置由内建的 autoAdjustOverflow 负责。
 * 外观不另做深色皮: 全站 antd 浮层(表头筛选下拉等)都直接吃 theme.ts 的令牌, 这里一并对齐。
 */

import { Popover } from "antd";

import { localizedField, useI18n } from "../../../i18n/I18nProvider";
import type { Locale } from "../../../i18n/messages";
import type { Translator } from "../../../lib/status";
import type { PortalGrantRow } from "../portalListPayload";

interface GrantPermissionSection {
  key: string;
  label: string;
  lines: string[];
}

/**
 * 浮层的滚动盒就是 antd 的 `.ant-popover-inner`(带 `role="tooltip"` 与 id 的那一层),
 * 所以尺寸约束挂在 `classNames.body` 上而不是自己再套一层。
 */
const POPOVER_BODY_CLASS = "max-h-80 max-w-[28rem] overflow-y-auto";

/** 单位是秒: 指针要从触发器走到浮层上, 关闭必须留出这段路程的时间。 */
const MOUSE_LEAVE_DELAY_SECONDS = 0.2;

export function GrantPermissionsCell({ row }: { row: PortalGrantRow }) {
  const { locale, t } = useI18n();
  const count = row.grants.length;
  const countText = t("portal.grants.permissionCount", { count });

  if (count === 0) {
    return <span className="whitespace-nowrap">{countText}</span>;
  }

  return (
    <Popover
      classNames={{ body: POPOVER_BODY_CLASS }}
      content={<GrantPermissionList row={row} locale={locale} t={t} />}
      mouseLeaveDelay={MOUSE_LEAVE_DELAY_SECONDS}
      placement="bottomLeft"
      trigger={["hover", "focus"]}
    >
      <button
        type="button"
        className="cursor-help whitespace-nowrap underline decoration-dotted decoration-ink-faint underline-offset-4"
      >
        {countText}
      </button>
    </Popover>
  );
}

/**
 * 浮层正文。
 *
 * `tabIndex={0}` 是给键盘用户的: 长列表在 `.ant-popover-inner` 上滚动, 焦点落在正文里
 * 方向键才滚得动最近的滚动祖先。
 */
function GrantPermissionList({ row, locale, t }: { row: PortalGrantRow; locale: Locale; t: Translator }) {
  return (
    <div className="space-y-2" tabIndex={0}>
      {buildSections(row, locale, t).map((section) => (
        <div key={section.key}>
          <p className="font-semibold text-ink-soft">{section.label}</p>
          <ul>
            {section.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** 按来源分组, 组内每行是「权限名 · 范围名」。来源顺序沿用后端下发的权限顺序。 */
function buildSections(row: PortalGrantRow, locale: Locale, t: Translator): GrantPermissionSection[] {
  const sections: GrantPermissionSection[] = [];
  const byKey = new Map<string, GrantPermissionSection>();

  for (const grant of row.grants) {
    const key = `${grant.source_type}:${grant.source_key ?? ""}`;
    let section = byKey.get(key);
    if (section === undefined) {
      section = { key, label: sourceLabel(row, grant, t), lines: [] };
      byKey.set(key, section);
      sections.push(section);
    }
    const permissionName = localizedField(locale, grant.permission_name, grant.permission_name_en);
    const scopeName = localizedField(locale, grant.scope_name, grant.scope_name_en);
    section.lines.push(`${permissionName} · ${scopeName}`);
  }

  return sections;
}

function sourceLabel(row: PortalGrantRow, grant: PortalGrantRow["grants"][number], t: Translator): string {
  switch (grant.source_type) {
    case "group": {
      const group = row.groups.find((item) => item.key === grant.source_key);
      return group ? group.name || group.key : (grant.source_key ?? grant.source_type);
    }
    case "direct":
      return t("portal.grants.source.direct");
    default:
      // 后端只产出 group / direct 两种来源; 出现第三种说明契约变了, 必须炸出来。
      throw new Error(`未知的授权来源类别：${grant.source_type}`);
  }
}
