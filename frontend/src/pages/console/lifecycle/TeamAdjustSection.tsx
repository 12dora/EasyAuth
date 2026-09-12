import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "../../../components/Button";
import { SelectInput } from "../../../components/Field";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useToast } from "../../../components/ui/Toast";
import { useUserOptionsByIds, userOptionName, userSecondaryLabel } from "../../../components/UserCombobox";
import type { UserOption } from "../../../components/UserCombobox";
import { UserSearchInput } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type { HandoverTaskDetail, HandoverTeamItemRow, HandoverUserRef } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";

export interface TeamAdjustSectionProps {
  task: HandoverTaskDetail;
  taskId: string;
  onChanged: () => void;
  canOperate: boolean;
}

/** 团队调整: 每行指定接任负责人或停用团队, 提交即生效。 */
export function TeamAdjustSection({ task, taskId, onChanged, canOperate }: TeamAdjustSectionProps) {
  const { t } = useI18n();
  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("handover.team.title")}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("handover.team.hint")}</p>
      </div>
      {task.team_items.length === 0 ? (
        <p className="text-body leading-5 text-ink-soft">{t("handover.team.empty")}</p>
      ) : (
        <ul className="grid gap-2.5">
          {task.team_items.map((item) => (
            <TeamAdjustRow key={item.id} item={item} taskId={taskId} onChanged={onChanged} canOperate={canOperate} />
          ))}
        </ul>
      )}
    </PanelSurface>
  );
}

function TeamAdjustRow({
  item,
  taskId,
  onChanged,
  canOperate,
}: {
  item: HandoverTeamItemRow;
  taskId: string;
  onChanged: () => void;
  canOperate: boolean;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [action, setAction] = useState<"assign_leader" | "deactivate">(
    item.action === "deactivate" ? "deactivate" : "assign_leader",
  );
  const [successorId, setSuccessorId] = useState(item.to_user?.user_id ?? "");
  const applyMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/lifecycle/handover-tasks/${taskId}/team-items/${item.id}`, {
        method: "PATCH",
        body: {
          action,
          ...(action === "assign_leader" ? { to_user_id: successorId.trim() } : {}),
        } satisfies JsonObject,
      }),
    onSuccess: onChanged,
    onError: (error: Error) => {
      toast.error(t("handover.team.applyFailed"), error.message);
    },
  });

  if (item.status !== "pending") {
    return (
      <li className="flex flex-wrap items-center justify-between gap-3 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2.5">
        <strong className="text-body text-ink">{item.team_name}</strong>
        <span className="text-body text-ink-soft">{teamItemDoneLabel(item, t)}</span>
      </li>
    );
  }

  return (
    <li className="space-y-2.5 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <strong className="min-w-32 text-body text-ink">{item.team_name}</strong>
        <SelectInput
          aria-label={`${item.team_name} ${t("common.actions")}`}
          className="w-56"
          value={action}
          disabled={!canOperate}
          onChange={(event) => setAction(event.currentTarget.value as "assign_leader" | "deactivate")}
        >
          <option value="assign_leader">{t("handover.team.assignLeader")}</option>
          <option value="deactivate">{t("handover.team.deactivate")}</option>
        </SelectInput>
        {action === "assign_leader" ? (
          <div className="min-w-56 flex-1">
            {canOperate ? (
              <UserSearchInput
                value={successorId}
                aria-label={`${item.team_name} ${t("handover.team.successor")}`}
                selectedOption={item.to_user?.name ? toUserOption(item.to_user, successorId) : null}
                onChange={setSuccessorId}
              />
            ) : (
              <SuccessorReadOnly userId={successorId} known={item.to_user} />
            )}
          </div>
        ) : null}
        <Button
          type="button"
          disabled={!canOperate || (action === "assign_leader" && !successorId.trim())}
          loading={applyMutation.isPending}
          onClick={() => applyMutation.mutate()}
        >
          {t("handover.team.apply")}
        </Button>
      </div>
    </li>
  );
}

function teamItemDoneLabel(item: HandoverTeamItemRow, t: Translator): string {
  if (item.status === "skipped") {
    return t("handover.team.doneSkipped");
  }
  if (item.action === "deactivate") {
    return t("handover.team.doneDeactivated");
  }
  return t("handover.team.doneAssigned", { name: personNameWithDepartment(item.to_user, t) });
}

/** 只读态: 已有姓名就展示, 只有 ID 时按 employee 口径解析, 解析失败仍回退到 ID。 */
function SuccessorReadOnly({ userId, known }: { userId: string; known: HandoverUserRef | null }) {
  const { t } = useI18n();
  const knownMatches = Boolean(known && known.user_id === userId && known.name);
  const lookupQuery = useUserOptionsByIds(userId && !knownMatches ? [userId] : [], "employee");
  const option = knownMatches
    ? toUserOption(known, userId)
    : (lookupQuery.data?.find((item) => item.user_id === userId) ?? toUserOption(known, userId));
  if (!userId) {
    return <span className="text-body text-ink-soft">-</span>;
  }
  const name = userOptionName(option ?? undefined, userId);
  const secondary = option ? userSecondaryLabel(option, t) : "";
  return (
    <span className="text-body text-ink-soft">
      {name}
      {secondary ? <span className="ml-2 text-caption text-ink-faint">{secondary}</span> : null}
    </span>
  );
}

function toUserOption(user: HandoverUserRef | null | undefined, expectedUserId: string): UserOption | null {
  if (!user || user.user_id !== expectedUserId) {
    return null;
  }
  return { user_id: user.user_id, name: user.name, department: user.department ?? "" };
}

function personNameWithDepartment(user: HandoverUserRef | null | undefined, t: Translator): string {
  if (!user) {
    return "-";
  }
  const name = userOptionName(user, user.user_id);
  const secondary = userSecondaryLabel(user, t);
  return secondary ? `${name} · ${secondary}` : name || "-";
}
