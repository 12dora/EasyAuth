import { useLayoutEffect, useRef, useState } from "react";

import { useRovingTabs } from "../../../components/useRovingTabs";
import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";
import type { WorkspaceTab, WorkspaceTabDescriptor } from "./workspaceTabs";

export function WorkspaceTabList({
  tabs,
  activeTab,
  onActivate,
}: {
  tabs: WorkspaceTabDescriptor[];
  activeTab: WorkspaceTab;
  onActivate: (key: WorkspaceTab) => void;
}) {
  const { t } = useI18n();
  const tabButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeTabIndex = tabs.findIndex((item) => item.key === activeTab);
  const onTabListKeyDown = useRovingTabs({
    activeKey: activeTab,
    items: tabs.map((item) => item.key),
    refs: tabButtonRefs,
    onActivate,
  });
  const indicatorStyle = useActiveTabIndicator(tabButtonRefs, activeTabIndex);

  return (
    <div
      className="relative mb-6 flex gap-1 overflow-x-auto border-b border-ink/12"
      role="tablist"
      aria-label={t("workspace.tablist")}
      onKeyDown={onTabListKeyDown}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 h-0.5 bg-accent transition-[left,width] duration-200 ease-out"
        style={{ left: indicatorStyle.left, width: indicatorStyle.width }}
      />
      {tabs.map((item, index) => (
        <button
          key={item.key}
          ref={(node) => {
            tabButtonRefs.current[index] = node;
          }}
          role="tab"
          id={`workspace-tab-${item.key}`}
          aria-selected={item.key === activeTab}
          aria-controls={`workspace-tabpanel-${item.key}`}
          tabIndex={item.key === activeTab ? 0 : -1}
          className={cn(
            "relative z-10 h-10 shrink-0 px-3 text-sm font-semibold transition-colors",
            item.key === activeTab
              ? "text-ink"
              : "text-ink-soft hover:text-ink",
          )}
          onClick={() => onActivate(item.key)}
          type="button"
        >
          {t(item.labelKey)}
        </button>
      ))}
    </div>
  );
}

/** 让下划线指示器跟随当前页签按钮的位置与宽度(含容器/窗口尺寸变化)。 */
function useActiveTabIndicator(
  tabButtonRefs: React.RefObject<Array<HTMLButtonElement | null>>,
  activeTabIndex: number,
) {
  const [indicatorStyle, setIndicatorStyle] = useState({ left: 0, width: 0 });

  useLayoutEffect(() => {
    const activeButton = tabButtonRefs.current[activeTabIndex];
    if (!activeButton) {
      return;
    }
    const updateIndicator = () => {
      setIndicatorStyle({
        left: activeButton.offsetLeft,
        width: activeButton.offsetWidth,
      });
    };

    updateIndicator();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateIndicator);
    observer?.observe(activeButton);
    if (activeButton.parentElement) {
      observer?.observe(activeButton.parentElement);
    }
    window.addEventListener("resize", updateIndicator);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateIndicator);
    };
  }, [activeTabIndex, tabButtonRefs]);

  return indicatorStyle;
}
