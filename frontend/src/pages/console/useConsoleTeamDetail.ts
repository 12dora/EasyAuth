import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { TeamMemberItem, TeamPayload } from "../../lib/domain";
import { TEAMS_LIST_QUERY_KEY } from "./ConsoleTeamList";
import type { TeamInfoFormPayload, TeamMemberCreatePayload, TeamMemberRole } from "./consoleTeamDetailModel";

/** 团队详情页的装载与全部变更(信息/启停/成员增删改角色)。 */
export function useConsoleTeamDetail() {
  const { t } = useI18n();
  const toast = useToast();
  const { teamId = "" } = useParams();
  const queryClient = useQueryClient();
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [addMemberDialogOpen, setAddMemberDialogOpen] = useState(false);
  const [disableConfirmOpen, setDisableConfirmOpen] = useState(false);
  const [memberPendingRemoval, setMemberPendingRemoval] = useState<TeamMemberItem | null>(null);
  const detailQueryKey = ["console", "teams", teamId];
  const mutationScope = { id: `console-team:${teamId}` };

  const teamQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: ({ signal }) => apiRequest<TeamPayload>(`/console/api/v1/teams/${teamId}`, { signal }),
    enabled: Boolean(teamId),
  });
  const team = teamQuery.data?.team;
  const members = team?.members ?? [];

  // 团队接口的每个变更都会回传最新 team, 直接写入详情缓存并失效列表, 避免多余的详情重取。
  const applyTeamPayload = async (payload: TeamPayload) => {
    await queryClient.cancelQueries({ queryKey: detailQueryKey, exact: true });
    queryClient.setQueryData(detailQueryKey, payload);
    void queryClient.invalidateQueries({ queryKey: TEAMS_LIST_QUERY_KEY });
  };

  const saveInfoMutation = useMutation({
    scope: mutationScope,
    mutationFn: (payload: TeamInfoFormPayload) =>
      apiRequest<TeamPayload>(`/console/api/v1/teams/${teamId}`, {
        method: "PATCH",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: async (payload) => {
      await applyTeamPayload(payload);
      setEditDialogOpen(false);
    },
  });
  const statusMutation = useMutation({
    scope: mutationScope,
    mutationFn: (isActive: boolean) =>
      apiRequest<TeamPayload>(`/console/api/v1/teams/${teamId}`, {
        method: "PATCH",
        body: { is_active: isActive },
      }),
    onSuccess: async (payload) => {
      await applyTeamPayload(payload);
      setDisableConfirmOpen(false);
    },
    onError: (error: Error) => {
      toast.error(t("console.teams.statusUpdateFailed"), error.message);
    },
  });
  const addMemberMutation = useMutation({
    scope: mutationScope,
    mutationFn: (payload: TeamMemberCreatePayload) =>
      apiRequest<TeamPayload>(`/console/api/v1/teams/${teamId}/members`, {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: async (payload) => {
      await applyTeamPayload(payload);
      setAddMemberDialogOpen(false);
    },
  });
  const changeRoleMutation = useMutation({
    scope: mutationScope,
    mutationFn: ({ memberId, role }: { memberId: number; role: TeamMemberRole }) =>
      apiRequest<TeamPayload>(`/console/api/v1/teams/${teamId}/members/${memberId}`, {
        method: "PATCH",
        body: { role },
      }),
    onSuccess: applyTeamPayload,
    onError: (error: Error) => {
      toast.error(t("console.teams.memberOperationFailed"), error.message);
    },
  });
  const removeMemberMutation = useMutation({
    scope: mutationScope,
    mutationFn: (memberId: number) =>
      apiRequest<TeamPayload>(`/console/api/v1/teams/${teamId}/members/${memberId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      await applyTeamPayload(payload);
      setMemberPendingRemoval(null);
    },
    onError: (error: Error) => {
      toast.error(t("console.teams.memberOperationFailed"), error.message);
    },
  });

  return {
    teamQuery,
    team,
    members,
    editDialogOpen,
    openEditDialog: () => {
      saveInfoMutation.reset();
      setEditDialogOpen(true);
    },
    // 提交进行中不允许关弹窗, 避免用户以为已取消但请求仍在飞。
    closeEditDialog: () => {
      if (!saveInfoMutation.isPending) {
        setEditDialogOpen(false);
      }
    },
    addMemberDialogOpen,
    openAddMemberDialog: () => {
      addMemberMutation.reset();
      setAddMemberDialogOpen(true);
    },
    closeAddMemberDialog: () => {
      if (!addMemberMutation.isPending) {
        setAddMemberDialogOpen(false);
      }
    },
    disableConfirmOpen,
    openDisableConfirm: () => {
      statusMutation.reset();
      setDisableConfirmOpen(true);
    },
    closeDisableConfirm: () => {
      if (!statusMutation.isPending) {
        setDisableConfirmOpen(false);
      }
    },
    memberPendingRemoval,
    setMemberPendingRemoval,
    cancelMemberRemoval: () => {
      if (!removeMemberMutation.isPending) {
        setMemberPendingRemoval(null);
      }
    },
    saveInfoMutation,
    statusMutation,
    addMemberMutation,
    changeRoleMutation,
    removeMemberMutation,
  };
}
