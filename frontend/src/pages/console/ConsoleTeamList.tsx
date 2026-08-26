import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCcw } from "lucide-react";
import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AppTable, serverTableQuery, useServerTable, type ColumnsType } from "../../components/antd/AppTable";
import {
  RowActionButton,
  RowActionLink,
  actionsColumn,
  dateTimeColumn,
  statusColumn,
  textColumn,
} from "../../components/antd/columns";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { PageState } from "../../components/ui/PageState";
import { useToast } from "../../components/ui/Toast";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject, ListPayload } from "../../lib/api";
import type { TeamPayload, TeamSummary } from "../../lib/domain";

/** 团队列表查询键前缀; 详情页失效列表时也用它。 */
export const TEAMS_LIST_QUERY_KEY = ["console", "teams", "list"];

export function teamLeadersLabel(leaders: TeamSummary["leaders"] | undefined): string {
  const names = (leaders ?? []).map((leader) => leader.name || leader.user_id).filter(Boolean);
  return names.length > 0 ? names.join(", ") : "—";
}

export function ConsoleTeamList() {
  const { t } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TeamSummary | null>(null);
  // 团队接口只支持 page/page_size, 没有任何过滤或排序参数, 因此列上不给表头筛选。
  const serverTable = useServerTable<TeamSummary>();
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
  const deleteMutation = useMutation({
    mutationFn: (team: TeamSummary) =>
      apiRequest(`/console/api/v1/teams/${team.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEAMS_LIST_QUERY_KEY });
      setDeleteTarget(null);
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
      setCreateDialogOpen(false);
      const teamId = payload.team?.id;
      if (teamId) {
        void navigate(`/console/teams/${teamId}`);
      }
    },
  });

  const columns = useMemo<ColumnsType<TeamSummary>>(
    () => [
      {
        key: "name",
        dataIndex: "name",
        title: t("console.teams.column.name"),
        ellipsis: true,
        render: (_value: unknown, team: TeamSummary) => <strong>{team.name}</strong>,
      },
      textColumn<TeamSummary>({
        key: "leaders",
        title: t("console.teams.column.leaders"),
        getValue: (team) => teamLeadersLabel(team.leaders),
        width: 220,
      }),
      textColumn<TeamSummary>({
        key: "member_count",
        title: t("console.teams.column.memberCount"),
        getValue: (team) => String(team.member_count ?? 0),
        width: 110,
      }),
      statusColumn<TeamSummary>({
        key: "status",
        title: t("common.status"),
        getValue: (team) => (team.is_active ? "active" : "inactive"),
        filter: false,
        options: [
          { value: "active", label: t("common.enabled"), tone: "evergreen" },
          { value: "inactive", label: t("common.disabled"), tone: "neutral" },
        ],
        width: 110,
      }),
      dateTimeColumn<TeamSummary>({
        key: "created_at",
        title: t("console.teams.column.createdAt"),
        sorter: false,
      }),
      actionsColumn<TeamSummary>({
        render: (team) => (
          <>
            <RowActionLink
              href={`/console/teams/${team.id}`}
              icon={<ArrowRight size={15} />}
              onClick={(event) => {
                event.preventDefault();
                void navigate(`/console/teams/${team.id}`);
              }}
            >
              {t("console.teams.view")}
            </RowActionLink>
            <RowActionButton type="button" variant="ghost-danger" onClick={() => setDeleteTarget(team)}>
              {t("common.delete")}
            </RowActionButton>
          </>
        ),
      }),
    ],
    [navigate, t],
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

interface TeamCreateFormPayload {
  name: string;
  description: string;
}

function TeamCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TeamCreateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      return;
    }
    onSubmit({ name: normalizedName, description: description.trim() });
  };

  return (
    <Dialog
      title={t("console.teams.create")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="create-team-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.create")}
          </Button>
        </>
      }
    >
      <form id="create-team-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.teams.createFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
