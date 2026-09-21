export const zhCN = {
  "systemHealth.description": "外部依赖的连通性与钉钉接口用量的统一观测入口。",
  "systemHealth.tablist": "状态健康页签",
  "systemHealth.tab.dependencies": "依赖状态",
  "systemHealth.tab.usage": "用量监控",
  "systemHealth.usage.loading": "正在加载用量监控",
  "systemHealth.usage.loadingDescription": "首次打开该页签时单独加载用量监控代码包。",
  "systemHealth.usage.chunkFailed": "用量监控代码包加载失败",

  "systemHealth.dependencies.heading": "依赖状态",
  "systemHealth.dependencies.description": "Authentik、钉钉等外部依赖最近一次探测的结果；筛选与排序都在本页完成。",
  "systemHealth.dependencies.runCheck": "立即检测",
  "systemHealth.dependencies.runCheckFailed": "依赖检测执行失败",
  "systemHealth.dependencies.loadFailed": "依赖状态加载失败",
  "systemHealth.dependencies.empty": "暂无依赖检测结果",
  "systemHealth.dependencies.emptyDescription": "点击「立即检测」发起一次依赖探测。",
  "systemHealth.dependencies.column.component": "组件",
  "systemHealth.dependencies.column.summary": "摘要",
  "systemHealth.dependencies.column.error": "错误",
  "systemHealth.dependencies.column.checkedAt": "检查时间",
} as const;

export const en: Record<keyof typeof zhCN, string> = {
  "systemHealth.description": "One place to watch external dependency health and DingTalk API usage.",
  "systemHealth.tablist": "System health tabs",
  "systemHealth.tab.dependencies": "Dependencies",
  "systemHealth.tab.usage": "Usage Monitor",
  "systemHealth.usage.loading": "Loading the usage monitor",
  "systemHealth.usage.loadingDescription": "The usage monitor bundle is fetched the first time this tab is opened.",
  "systemHealth.usage.chunkFailed": "Failed to load the usage monitor bundle",

  "systemHealth.dependencies.heading": "Dependencies",
  "systemHealth.dependencies.description":
    "Latest probe result for external dependencies such as Authentik and DingTalk; filtering and sorting happen on this page.",
  "systemHealth.dependencies.runCheck": "Run check now",
  "systemHealth.dependencies.runCheckFailed": "Dependency check failed",
  "systemHealth.dependencies.loadFailed": "Failed to load dependency status",
  "systemHealth.dependencies.empty": "No dependency check results",
  "systemHealth.dependencies.emptyDescription": "Use “Run check now” to probe the dependencies.",
  "systemHealth.dependencies.column.component": "Component",
  "systemHealth.dependencies.column.summary": "Summary",
  "systemHealth.dependencies.column.error": "Error",
  "systemHealth.dependencies.column.checkedAt": "Checked at",
};
