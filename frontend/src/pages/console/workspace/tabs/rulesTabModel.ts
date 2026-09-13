import type { ApprovalRuleItem } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";

export type RuleTargetType = "authorization_group" | "permission";
export type EditableApprovalRule = ApprovalRuleItem & { blocking?: boolean; status?: string };

export const emptyRuleForm = {
  target_type: "authorization_group" as RuleTargetType,
  target_key: "",
  approverUserIds: [] as string[],
};

export type RuleFormState = typeof emptyRuleForm;

export function targetTypeLabel(t: Translator, value: string | undefined): string {
  if (value === "permission") {
    return t("console.rules.targetType.permission");
  }
  if (value === "authorization_group") {
    return t("console.rules.targetType.authorizationGroup");
  }
  return value ?? "-";
}

export function normalizeTargetType(value: string | undefined): RuleTargetType {
  return value === "permission" ? "permission" : "authorization_group";
}

export function isBlocking(rule: EditableApprovalRule): boolean {
  return rule.blocking === true || rule.status === "blocking";
}
