import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type {
  AppListPayload,
  AppSummary,
  OnboardingTemplateItemRow,
  OnboardingTemplateRow,
} from "../../../lib/domain";
import { grantTypeLabel } from "../../../lib/status";
import type { Translator } from "../../../lib/status";

export type TemplateItemKind = "group" | "permission";

export interface TemplateItemDraft {
  app_key: string;
  kind: TemplateItemKind;
  key: string;
  name: string;
  scope_key: string;
  grant_type: string;
  duration_days: number | null;
}

export interface TemplateFormPayload {
  name: string;
  description: string;
  is_active: boolean;
  items: TemplateItemDraft[];
}

export function templateItemDrafts(template: OnboardingTemplateRow | null): TemplateItemDraft[] {
  return (template?.items ?? []).map((item: OnboardingTemplateItemRow) => ({
    app_key: item.app_key,
    kind: item.kind === "group" ? "group" : "permission",
    key: item.key,
    name: item.name,
    scope_key: item.scope_key,
    grant_type: item.grant_type,
    duration_days: item.duration_days,
  }));
}

export function templateRequestBody(payload: TemplateFormPayload): JsonObject {
  return {
    name: payload.name,
    description: payload.description,
    is_active: payload.is_active,
    items: payload.items.map((item) => ({
      app_key: item.app_key,
      ...(item.kind === "group" ? { authorization_group_key: item.key } : { permission_key: item.key }),
      ...(item.scope_key ? { scope_key: item.scope_key } : {}),
      grant_type: item.grant_type,
      ...(item.grant_type === "timed" && item.duration_days ? { duration_days: item.duration_days } : {}),
    })),
  } satisfies JsonObject;
}

export function templateItemLine(
  t: Translator,
  item: { name: string; key: string; scope_key: string; grant_type: string; duration_days: number | null; kind: string },
): string {
  const kindLabel = item.kind === "group" ? t("onboarding.editor.kind.group") : t("onboarding.editor.kind.permission");
  const term =
    item.grant_type === "timed" && item.duration_days
      ? t("onboarding.item.timedDays", { days: item.duration_days })
      : grantTypeLabel(t, item.grant_type);
  const scope = item.scope_key ? ` · ${item.scope_key}` : "";
  return `${kindLabel} · ${item.name || item.key}${scope} · ${term}`;
}

export async function fetchAllSelectorApps(): Promise<AppSummary[]> {
  const firstPage = await apiRequest<AppListPayload>("/console/api/v1/apps?page=1&page_size=100");
  const pagination = firstPage.pagination;
  if (!pagination) {
    throw new Error("app_selector_missing_pagination");
  }
  const apps = [...itemsFromPayload<AppSummary>(firstPage)];
  for (let page = 2; page <= pagination.total_pages; page += 1) {
    const payload = await apiRequest<AppListPayload>(`/console/api/v1/apps?page=${page}&page_size=${pagination.page_size}`);
    apps.push(...itemsFromPayload<AppSummary>(payload));
  }
  return apps;
}
