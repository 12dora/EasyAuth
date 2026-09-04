/**
 * 「我的权限」表格的权限详情单元格: 表格里只显示条数, 悬停或聚焦时用浮层逐条列出。
 *
 * 一条授权展开后动辄几十项权限, 原来把它们拼成一串塞进单元格, 行高被撑到几十行、
 * 整张表没法看; 条数 + 浮层既保住了「我到底有多少权限」这个第一眼信息,
 * 又让明细随时可查。浮层按来源分组(角色的权限归在角色名下, 直接授权单列一组),
 * 因为员工要回答的往往是「这项权限是哪个角色带来的」。
 */

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { localizedField, useI18n } from "../../../i18n/I18nProvider";
import type { Locale } from "../../../i18n/messages";
import type { Translator } from "../../../lib/status";
import type { PortalGrantRow } from "../portalListPayload";

interface GrantPermissionSection {
  key: string;
  label: string;
  lines: string[];
}

export function GrantPermissionsCell({ row }: { row: PortalGrantRow }) {
  const { locale, t } = useI18n();
  const count = row.grants.length;
  const countText = t("portal.grants.permissionCount", { count });

  if (count === 0) {
    return <span className="whitespace-nowrap">{countText}</span>;
  }

  return (
    <HoverTooltip label={countText}>
      <div className="space-y-2">
        {buildSections(row, locale, t).map((section) => (
          <div key={section.key}>
            <p className="font-semibold text-paper/70">{section.label}</p>
            <ul>
              {section.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </HoverTooltip>
  );
}

/**
 * 悬停/聚焦浮层。
 *
 * 浮层挂到 document.body 上而不是像 InfoTip 那样在原地绝对定位: antd 表格给
 * `.ant-table-content` 挂了 `overflow: auto hidden`(横向滚动容器), 单元格里的
 * 绝对定位浮层会被这一层直接裁掉, 只剩贴着单元格的一条。
 */
function HoverTooltip({ label, children }: { label: string; children: ReactNode }) {
  const tooltipId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState({ top: 0, left: 0 });

  useLayoutEffect(() => {
    const trigger = triggerRef.current;
    if (!open || trigger === null) {
      return;
    }
    const rect = trigger.getBoundingClientRect();
    setAnchor({ top: rect.bottom + 6, left: rect.left });
  }, [open]);

  return (
    <span
      className="inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-describedby={open ? tooltipId : undefined}
        className="cursor-help whitespace-nowrap underline decoration-dotted decoration-ink-faint underline-offset-4"
        onBlur={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      >
        {label}
      </button>
      {open
        ? createPortal(
            <div
              id={tooltipId}
              role="tooltip"
              style={{ top: anchor.top, left: anchor.left }}
              className="fixed z-50 max-h-80 max-w-[28rem] overflow-y-auto rounded-[3px] bg-ink px-3 py-2 text-xs font-normal normal-case leading-5 tracking-normal text-paper shadow-lg"
            >
              {children}
            </div>,
            document.body,
          )
        : null}
    </span>
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
