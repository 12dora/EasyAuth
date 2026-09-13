import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  AppTable,
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
  type ServerSortState,
} from "../../components/antd/AppTable";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { PageState } from "../../components/ui/PageState";
import { useToast } from "../../components/ui/Toast";
import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject, ListPayload } from "../../lib/api";
import type { TeamPayload, TeamSummary } from "../../lib/domain";
import { buildTeamColumns, teamLeadersLabel } from "./consoleTeamColumns";
import { TeamCreateDialog, type TeamCreateFormPayload } from "./TeamCreateDialog";

/** 团队列表查询键前缀; 详情页失效列表时也用它。 */
export const TEAMS_LIST_QUERY_KEY = ["console", "teams", "list"];

export { teamLeadersLabel };

/**
 * 列 key -> 后端 `ordering` 字段。
 */
const TEAM_ORDERING_FIELDS = {
  name: "name",
  leaders: "leaders",
  status: "status",
  created_at: "created_at",
  member_count: "member_count",
} as const;

export function ConsoleTeamList() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TeamSummary | null>(null);
  // 团队接口没有过滤参数(因此列上不给表头筛选), 但支持单字段 ordering。
  const serverTable = useServerTable<TeamSummary>({
    sortParam: ORDERING_PARAM,
    serializeSort: orderingSerializer(TEAM_ORDERING_FIELDS),
  });
  const sort: ServerSortState = serverTable.query;
  const teamsSearch = serverTableQuery(serverTable.params);
  const teamsQuery = useQuery({
    // 列表键多带一段 "list": 详情键是 ["console","teams",teamId],
    // 分成两支后详情页可以只失效列表而不牵动自己的详情缓存。
    queryKey: [...TEAMS_LIST_QUERY_KEY, teamsSearch],
    queryFn: () => apiRequest<ListPayload<TeamSummary>>(`/console/api/v1/teams?${teamsSearch}`),
    placeholderData: (previous) => previous,
  });
  const teams = itemsFromPayload<TeamSummary>(teamsQuery.data);
  serverTable.setTotal(teamsQuery.data?.pagination?.total_items);
  const { createMutation, deleteMutation } = useConsoleTeamMutations({
    navigate,
    onCreated: () => setCreateDialogOpen(false),
    onDeleted: () => setDeleteTarget(null),
  });

  // 排序在后端做: 每一个数据列都过 serverSortColumn(sorter 只当开关、指示器受控)。
  const columns = useMemo(
    () => buildTeamColumns({ navigate, sort, t, onDelete: setDeleteTarget }),
    [navigate, sort, t],
  );

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("console.teams.title")}
        description={t("console.teams.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={teamsQuery.isFetching} onClick={() => void teamsQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
              {t("console.teams.create")}
            </Button>
          </>
        }
      />
      {teamsQuery.error && teams.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("console.teams.loadFailed")} message={(teamsQuery.error as Error).message} />
      ) : null}
      {teamsQuery.error && teams.length === 0 ? (
        <PageState
          tone="signal"
          title={t("console.teams.loadFailed")}
          description={(teamsQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={teamsQuery.isFetching} onClick={() => void teamsQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <section className="space-y-3">
          <AppTable<TeamSummary>
            {...serverTable.tableProps}
            columns={columns}
            dataSource={teams}
            emptyDescription={t("console.teams.empty.description")}
            emptyTitle={t("console.teams.empty.title")}
            loading={teamsQuery.isLoading || teamsQuery.isPlaceholderData}
            minWidth={960}
            rowKey="id"
          />
        </section>
      )}
      {createDialogOpen ? (
        <TeamCreateDialog
          errorMessage={createMutation.error ? (createMutation.error as Error).message : ""}
          isSubmitting={createMutation.isPending}
          onClose={() => setCreateDialogOpen(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />
      ) : null}
      {deleteTarget ? (
        <ConfirmDialog
          title={t("console.teams.deleteTitle")}
          message={t("console.teams.deleteMessage", { name: deleteTarget.name })}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      ) : null}
    </>
  );
}

function useConsoleTeamMutations({
  navigate,
  onCreated,
  onDeleted,
}: {
  navigate: ReturnType<typeof useNavigate>;
  onCreated: () => void;
  onDeleted: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const deleteMutation = useMutation({
    mutationFn: (team: TeamSummary) =>
      apiRequest(`/console/api/v1/teams/${team.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_LIST_QUERY_KEY });
      onDeleted();
      toast.success(t("console.teams.deleteSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.teams.deleteFailed"), error.message);
    },
  });
  const createMutation = useMutation({
    mutationFn: (payload: TeamCreateFormPayload) =>
      apiRequest<TeamPayload>("/console/api/v1/teams", {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_LIST_QUERY_KEY });
      onCreated();
      const teamId = payload.team?.id;
      if (teamId) {
        void navigate(`/console/teams/${teamId}`);
      }
    },
  });
  return { createMutation, deleteMutation };
}
