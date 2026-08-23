/** 定义 Manifest 导入数据结构与无副作用的差异转换。 */

export type ManifestDiffItem = {
  type?: string;
  key?: string;
  name?: string;
  before?: unknown;
  after?: unknown;
};

export type ManifestPreviewPayload = {
  diff?: {
    added?: ManifestDiffItem[];
    changed?: ManifestDiffItem[];
    removed?: ManifestDiffItem[];
  };
  changes?: Array<{ action?: string; key?: string; parent_key?: string }>;
  preview_id?: string;
};

export type ManifestPreviewBinding = {
  payload: ManifestPreviewPayload;
  contentFingerprint: string;
  generation: number;
};

export type ManifestImportPayload = {
  catalog_version?: string | number;
  template_version?: string | number;
};

export type ManifestVersion = {
  version?: string;
  catalog_version?: string;
  imported_at?: string;
  created_at?: string;
  imported_by?: string;
};

export function manifestVersionsQueryPrefix(appKey: string) {
  return ["console", "app", appKey, "manifest-versions"] as const;
}

export function diffFromChanges(
  changes: Array<{ action?: string; key?: string; parent_key?: string }>,
): NonNullable<ManifestPreviewPayload["diff"]> {
  return {
    added: changes.filter((change) => change.action?.startsWith("create")).map(changeItem),
    changed: changes.filter((change) => change.action?.startsWith("update")).map(changeItem),
    removed: changes.filter((change) => change.action?.startsWith("deactivate")).map(changeItem),
  };
}

function changeItem(change: { action?: string; key?: string; parent_key?: string }): ManifestDiffItem {
  return {
    type: change.action,
    key: change.key,
    name: change.parent_key,
  };
}

export function manifestContentFingerprint(content: string): string {
  // 保留规范化后的完整内容作为同步身份, 避免非加密短哈希碰撞后确认错误预览。
  return content.replace(/\r\n?/g, "\n").trim();
}
