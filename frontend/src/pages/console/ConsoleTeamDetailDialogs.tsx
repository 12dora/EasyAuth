import type { TeamDetail } from "../../lib/domain";
import {
  TeamDisableConfirmDialog,
  TeamInfoDialog,
  TeamMemberCreateDialog,
  TeamMemberRemoveDialog,
} from "./ConsoleTeamDialogs";
import type { useConsoleTeamDetail } from "./useConsoleTeamDetail";

/** 团队详情页的四个弹窗: 编辑信息 / 新增成员 / 停用确认 / 移除成员确认。 */
export function ConsoleTeamDetailDialogs({
  page,
  team,
}: {
  page: ReturnType<typeof useConsoleTeamDetail>;
  team: TeamDetail | undefined;
}) {
  const { saveInfoMutation, statusMutation, addMemberMutation, removeMemberMutation, memberPendingRemoval } = page;

  return (
    <>
      {page.editDialogOpen && team ? (
        <TeamInfoDialog
          team={team}
          errorMessage={saveInfoMutation.error ? (saveInfoMutation.error as Error).message : ""}
          isSubmitting={saveInfoMutation.isPending}
          onClose={page.closeEditDialog}
          onSubmit={(payload) => saveInfoMutation.mutate(payload)}
        />
      ) : null}
      {page.addMemberDialogOpen ? (
        <TeamMemberCreateDialog
          errorMessage={addMemberMutation.error ? (addMemberMutation.error as Error).message : ""}
          isSubmitting={addMemberMutation.isPending}
          onClose={page.closeAddMemberDialog}
          onSubmit={(payload) => addMemberMutation.mutate(payload)}
        />
      ) : null}
      {page.disableConfirmOpen && team ? (
        <TeamDisableConfirmDialog
          team={team}
          isSubmitting={statusMutation.isPending}
          onClose={page.closeDisableConfirm}
          onConfirm={() => statusMutation.mutate(false)}
        />
      ) : null}
      {memberPendingRemoval ? (
        <TeamMemberRemoveDialog
          member={memberPendingRemoval}
          isSubmitting={removeMemberMutation.isPending}
          onClose={page.cancelMemberRemoval}
          onConfirm={() => removeMemberMutation.mutate(memberPendingRemoval.id)}
        />
      ) : null}
    </>
  );
}
