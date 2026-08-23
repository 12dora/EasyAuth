import type { TeamDetail, TeamLeaderRef } from "../../lib/domain";
import type { Translator } from "../../lib/status";

export type TeamMemberRole = "leader" | "member";

export interface TeamInfoFormPayload {
  name: string;
  description: string;
}

export interface TeamMemberCreatePayload {
  user_id: string;
  role: TeamMemberRole;
}

export function teamMemberRoleLabel(t: Translator, role: string): string {
  if (role === "leader") {
    return t("console.teams.role.leader");
  }
  if (role === "member") {
    return t("console.teams.role.member");
  }
  return role || "-";
}

/** 详情页展示用的团队摘要: 详情未到时全部落到占位, 视图层不再逐字段判空。 */
export interface TeamInfoView {
  hasTeam: boolean;
  name: string;
  isActive: boolean;
  leaders: TeamLeaderRef[] | undefined;
  memberCount: number;
  createdAt: string | null | undefined;
  updatedAt: string | null | undefined;
  description: string;
}

export function teamInfoView(team: TeamDetail | undefined, memberCountFallback: number): TeamInfoView {
  if (!team) {
    return {
      hasTeam: false,
      name: "-",
      isActive: false,
      leaders: undefined,
      memberCount: memberCountFallback,
      createdAt: undefined,
      updatedAt: undefined,
      description: "",
    };
  }
  return {
    hasTeam: true,
    name: team.name,
    isActive: team.is_active,
    leaders: team.leaders,
    memberCount: team.member_count,
    createdAt: team.created_at,
    updatedAt: team.updated_at,
    description: team.description ?? "",
  };
}
