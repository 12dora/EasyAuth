import { useRef } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/PageHeader";
import { PageState } from "../../../components/ui/PageState";
import { useActiveTabIndicator, useRovingTabs } from "../../../components/useRovingTabs";
import { useI18n } from "../../../i18n/I18nProvider";
import type { MessageKey } from "../../../i18n/messages";
import { cn } from "../../../lib/cn";
import { DependencyStatusTab } from "./DependencyStatusTab";
import { LazyChunkBoundary } from "./LazyChunkBoundary";

/**
 * 用量监控单独成块: 图表(recharts)只在打开该页签时才下载, 依赖状态页签不为它买单。
 * 契约规定 UsageMonitorTab 是默认导出且不收 props。
 *
 * 工厂放在模块级: LazyChunkBoundary 重试时要按同一个引用重新 import。
 */
const loadUsageMonitorTab = () => import("./UsageMonitorTab");

const TABS = [
  { key: "dependencies", labelKey: "systemHealth.tab.dependencies" },
  { key: "usage", labelKey: "systemHealth.tab.usage" },
] as const satisfies readonly { key: string; labelKey: MessageKey }[];

export type SystemHealthTab = (typeof TABS)[number]["key"];

const TAB_KEYS: readonly SystemHealthTab[] = TABS.map((tab) => tab.key);
const TAB_PARAM = "tab";
const DEFAULT_TAB: SystemHealthTab = "dependencies";

function isSystemHealthTab(value: string | null): value is SystemHealthTab {
  return TABS.some((tab) => tab.key === value);
}

/**
 * 「状态健康」页: 依赖状态 + 用量监控两个页签。
 *
 * 当前页签由 URL 的 `?tab=` 承载(可深链、可分享), 未给或取值非法时回落依赖状态;
 * 切换页签保留 URL 上的其余查询参数, 页签自身的筛选条件因此不会被切换清空。
 */
export function SystemHealthPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get(TAB_PARAM);
  const activeTab: SystemHealthTab = isSystemHealthTab(requestedTab) ? requestedTab : DEFAULT_TAB;

  const activateTab = (key: SystemHealthTab) => {
    const next = new URLSearchParams(searchParams);
    next.set(TAB_PARAM, key);
    setSearchParams(next);
  };

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t("nav.console.systemHealth")}
        description={t("systemHealth.description")}
      />
      <SystemHealthTabList activeTab={activeTab} onActivate={activateTab} />
      <div
        key={activeTab}
        id={`system-health-tabpanel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`system-health-tab-${activeTab}`}
      >
        {activeTab === "usage" ? (
          <LazyChunkBoundary
            fallback={
              <PageState
                title={t("systemHealth.usage.loading")}
                description={t("systemHealth.usage.loadingDescription")}
              />
            }
            loader={loadUsageMonitorTab}
            render={(Chunk) => <Chunk />}
            title={t("systemHealth.usage.chunkFailed")}
          />
        ) : (
          <DependencyStatusTab />
        )}
      </div>
    </>
  );
}

function SystemHealthTabList({
  activeTab,
  onActivate,
}: {
  activeTab: SystemHealthTab;
  onActivate: (key: SystemHealthTab) => void;
}) {
  const { t } = useI18n();
  const tabButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeTabIndex = TABS.findIndex((item) => item.key === activeTab);
  const onTabListKeyDown = useRovingTabs({
    activeKey: activeTab,
    items: TAB_KEYS,
    refs: tabButtonRefs,
    onActivate,
  });
  const indicatorStyle = useActiveTabIndicator(tabButtonRefs, activeTabIndex);

  return (
    <div
      className="relative mb-6 flex gap-1 overflow-x-auto border-b border-ink/12"
      role="tablist"
      aria-label={t("systemHealth.tablist")}
      onKeyDown={onTabListKeyDown}
    >
      {/* 位移与缓动与侧边栏当前项指示灯同一套(220ms, cubic-bezier(0.22, 1, 0.36, 1))。 */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 h-0.5 bg-accent transition-[left,width] duration-[220ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none"
        data-testid="system-health-tab-indicator"
        style={{ left: indicatorStyle.left, width: indicatorStyle.width }}
      />
      {TABS.map((item, index) => (
        <button
          key={item.key}
          ref={(node) => {
            tabButtonRefs.current[index] = node;
          }}
          role="tab"
          id={`system-health-tab-${item.key}`}
          aria-selected={item.key === activeTab}
          aria-controls={`system-health-tabpanel-${item.key}`}
          tabIndex={item.key === activeTab ? 0 : -1}
          className={cn(
            "relative z-10 h-10 shrink-0 px-3 text-sm font-semibold transition-colors",
            item.key === activeTab ? "text-ink" : "text-ink-soft hover:text-ink",
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
