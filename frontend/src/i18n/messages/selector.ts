export const zhCN = {
  "userSelect.searchPlaceholder": "搜索姓名、拼音或邮箱",
  "userSelect.searchHint": "输入姓名或用户 ID 搜索",

  "userSelect.loading": "搜索中…",

  "userSelect.empty": "未找到匹配用户",

  "userSelect.loadFailed": "候选用户加载失败，请重试。",

  "userSelect.remove": "移除 {name}",

  "selector.ariaLabel": "权限选择",

  "selector.column.permission": "权限",
  "selector.column.key": "权限 Key",
  "selector.column.scope": "权限范围",

  "selector.selectAppFirst.title": "选择应用后加载权限目录",
  "selector.selectAppFirst.description": "直接权限可留空，也可在应用目录加载后勾选具体权限。",

  "selector.loading.title": "权限目录加载中",
  "selector.loading.description": "正在读取直接权限目录。",

  "selector.loadFailed.title": "权限目录加载失败",

  "selector.empty.title": "暂无可选直接权限",
  "selector.empty.description": "当前应用没有可单独选择的权限，可仅选择权限组。",

  "selector.emptySelected.title": "当前没有已选直接权限",
  "selector.emptySelected.description": "关闭仅看已选后可继续浏览并选择权限。",

  "selector.toolbar.status": "权限选择状态",
  "selector.toolbar.selectedCount": "已选 {count} 项",
  "selector.toolbar.showSelectedOnly": "仅看已选",
  "selector.toolbar.expandAll": "展开全部",
  "selector.toolbar.collapseAll": "折叠全部",
  "selector.toolbar.selectAll": "全选",
  "selector.toolbar.selectScopeMenu": "展开全选范围选项",
  "selector.toolbar.clear": "清空",

  "selector.scope.self": "本人",
  "selector.scope.managedUsers": "管理范围",
  "selector.scope.all": "全部",
  "selector.scope.coveredByGroup": "已包含在所选权限组",
  "selector.scope.grantedByOrganization": "由组织授权下发",
  "selector.scope.lockedByOrganizationAdmin": "由组织授权下发，请在「组织授权」中调整",
  "selector.scope.lockedByOrganizationEmployee": "由组织授权自动获得，无需申请",

  "selector.group.collapse": "收起",
  "selector.group.expand": "展开",
  "selector.group.noScope": "权限组无权限范围",

  "selector.permission.noScope": "{permissionKey} 无权限范围",

  "selector.selectGroupScope": "选择权限组 {groupKey} {scopeName}",

  "selector.selectPermissionScope": "选择 {permissionKey} {scopeName}",
} as const;

export const en: Record<keyof typeof zhCN, string> = {
  "userSelect.searchPlaceholder": "Search name, pinyin or email",
  "userSelect.searchHint": "Search by name or user ID",

  "userSelect.loading": "Searching…",

  "userSelect.empty": "No matching users",

  "userSelect.loadFailed": "Failed to load user suggestions. Try again.",

  "userSelect.remove": "Remove {name}",

  "selector.ariaLabel": "Permission selection",

  "selector.column.permission": "Permission",
  "selector.column.key": "Permission Key",
  "selector.column.scope": "Scope",

  "selector.selectAppFirst.title": "Select an application to load its permission catalog",
  "selector.selectAppFirst.description": "Direct permissions are optional; pick specific permissions once the catalog is loaded.",

  "selector.loading.title": "Loading permission catalog",
  "selector.loading.description": "Loading direct permissions.",

  "selector.loadFailed.title": "Failed to load permission catalog",

  "selector.empty.title": "No direct permissions available",
  "selector.empty.description": "This application has no individually selectable permissions; choose authorization groups only.",

  "selector.emptySelected.title": "No direct permissions selected",
  "selector.emptySelected.description": "Turn off \"Selected only\" to keep browsing and selecting permissions.",

  "selector.toolbar.status": "Permission selection status",
  "selector.toolbar.selectedCount": "{count} selected",
  "selector.toolbar.showSelectedOnly": "Selected only",
  "selector.toolbar.expandAll": "Expand all",
  "selector.toolbar.collapseAll": "Collapse all",
  "selector.toolbar.selectAll": "Select all",
  "selector.toolbar.selectScopeMenu": "Open select-by-scope options",
  "selector.toolbar.clear": "Clear",

  "selector.scope.self": "Self",
  "selector.scope.managedUsers": "Managed users",
  "selector.scope.all": "All",
  "selector.scope.coveredByGroup": "Included in the selected group",
  "selector.scope.grantedByOrganization": "Granted by organization",
  "selector.scope.lockedByOrganizationAdmin": "Granted by organization policy. Adjust it under Organization grants.",
  "selector.scope.lockedByOrganizationEmployee": "Granted automatically by organization policy. No request needed.",

  "selector.group.collapse": "Collapse",
  "selector.group.expand": "Expand",
  "selector.group.noScope": "Permission group has no scopes",

  "selector.permission.noScope": "{permissionKey} has no scopes",

  "selector.selectGroupScope": "Select group {groupKey} {scopeName}",

  "selector.selectPermissionScope": "Select {permissionKey} {scopeName}",
};
