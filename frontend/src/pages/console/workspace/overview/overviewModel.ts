import type { AppSummary, ConfigurationIssue, ConfigurationStatus } from "../../../../lib/domain";
import type { BadgeTone, Translator } from "../../../../lib/status";

export interface AppPatchPayload {
  name: string;
  description: string;
}

export interface MembershipCreatePayload {
  user_id: string;
  role: MembershipRole;
}

export interface MembershipItem {
  id: number;
  user_id: string;
  role: MembershipRole | string;
  is_active?: boolean;
}

export type MembershipRole = "owner" | "developer";

export function roleLabel(t: Translator, role: string): string {
  if (role === "owner") {
    return t("console.overview.role.owner");
  }
  if (role === "developer") {
    return t("console.overview.role.developer");
  }
  return role || "-";
}

export function normalizeStatusBannerTone(tone: BadgeTone) {
  return tone === "faint" || tone === "ink" ? "neutral" : tone;
}

export interface OverviewSummary {
  issues: ConfigurationIssue[];
  status: string | undefined;
  issueCount: number;
}

/** 概览头部数据: 配置问题清单以应用摘要为准, 缺失时回落到状态接口返回的条数。 */
export function deriveOverviewSummary(app: AppSummary | undefined, statusPayload: ConfigurationStatus | undefined): OverviewSummary {
  const issues = statusPayload?.data ?? [];
  const summaryIssueCount = app?.configuration_summary?.issue_count;
  return {
    issues,
    status: statusPayload?.status ?? app?.configuration_status,
    issueCount: summaryIssueCount ?? issues.length,
  };
}

export function overviewMetricValues(app: AppSummary | undefined) {
  return {
    authorizationGroupCount: app?.authorization_group_count ?? 0,
    permissionCount: app?.permission_count ?? 0,
    credentialCount: app?.active_credential_count ?? 0,
  };
}
