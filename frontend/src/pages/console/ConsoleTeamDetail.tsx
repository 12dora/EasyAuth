import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCcw } from "lucide-react";
import { Fragment, type FormEvent } from "react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TableActionCell, TableRowActionButton } from "../../components/ui/TableActions";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { Dialog } from "../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useToast } from "../../components/ui/Toast";
import { UserSearchInput } from "../../components/UserSelect";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { TeamDetail, TeamMemberItem, TeamPayload } from "../../lib/domain";
import { formatDateTime } from "../../lib/status";
import type { Translator } from "../../lib/status";
import { teamLeadersLabel } from "./ConsoleTeamList";

type TeamMemberRole = "leader" | "member";

interface TeamInfoFormPayload {
  name: string;
  description: string;
}

interface TeamMemberCreatePayload {
  user_id: string;
  role: TeamMemberRole;
}

export function ConsoleTeamDetail() {
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
    void queryClient.invalidateQueries({ queryKey: ["console", "teams"], exact: true });
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

  const memberMutationPending = changeRoleMutation.isPending || removeMemberMutation.isPending;
  const memberColumns = teamMemberTableColumns({
    t,
    disabled: memberMutationPending,
    onToggleRole: (member) =>
      changeRoleMutation.mutate({ memberId: member.id, role: member.role === "leader" ? "member" : "leader" }),
    onRemove: (member) => setMemberPendingRemoval(member),
  });
  const memberTable = useReactTable({
    data: members,
    columns: memberColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (teamQuery.error && !team) {
    return (
      <PageState
        tone="signal"
        title={t("console.teams.loadFailed")}
        description={(teamQuery.error as Error).message}
        action={
          <Button icon={<RefreshCcw size={16} />} loading={teamQuery.isFetching} onClick={() => void teamQuery.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={team?.name ?? "-"}
        description={team?.description || undefined}
        actions={<ButtonLink to="/console/teams">{t("console.teams.backToList")}</ButtonLink>}
      />
      {teamQuery.error && team ? (
        <StatusBanner tone="signal" title={t("console.teams.loadFailed")} message={(teamQuery.error as Error).message} />
      ) : null}
      <section className="space-y-6">
        <PanelSurface padding="lg" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">{t("console.teams.info")}</h2>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                disabled={!team || saveInfoMutation.isPending}
                onClick={() => {
                  saveInfoMutation.reset();
                  setEditDialogOpen(true);
                }}
              >
                {t("common.edit")}
              </Button>
              {team?.is_active ? (
                <Button
                  type="button"
                  variant="ghost-danger"
                  disabled={statusMutation.isPending}
                  onClick={() => {
                    statusMutation.reset();
                    setDisableConfirmOpen(true);
                  }}
                >
                  {t("common.disable")}
                </Button>
              ) : (
                <Button
                  type="button"
                  disabled={!team || statusMutation.isPending}
                  loading={statusMutation.isPending}
                  onClick={() => statusMutation.mutate(true)}
                >
                  {t("common.enable")}
                </Button>
              )}
            </div>
          </div>
          <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
            <TeamInfoItem label={t("console.teams.column.name")} value={team?.name ?? "-"} />
            <TeamInfoItem
              label={t("common.status")}
              value={
                <Badge tone={team?.is_active ? "evergreen" : "neutral"}>
                  {team?.is_active ? t("common.enabled") : t("common.disabled")}
                </Badge>
              }
            />
            <TeamInfoItem label={t("console.teams.column.leaders")} value={teamLeadersLabel(team?.leaders)} />
            <TeamInfoItem label={t("console.teams.column.memberCount")} value={team?.member_count ?? members.length} />
            <TeamInfoItem label={t("console.teams.column.createdAt")} value={formatDateTime(team?.created_at)} />
            <TeamInfoItem label={t("common.updatedAt")} value={formatDateTime(team?.updated_at)} />
          </dl>
          {team?.description ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{team.description}</p> : null}
        </PanelSurface>
        <PanelSurface padding="lg" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">{t("console.teams.members")}</h2>
            <Button
              type="button"
              variant="primary"
              icon={<Plus size={16} />}
              disabled={!team}
              onClick={() => {
                addMemberMutation.reset();
                setAddMemberDialogOpen(true);
              }}
            >
              {t("console.teams.addMember")}
            </Button>
          </div>
          <TableFrame>
            <TableRoot>
              <TableHead>
                {memberTable.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHeaderCell key={header.id}>
                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      </TableHeaderCell>
                    ))}
                  </TableRow>
                ))}
              </TableHead>
              <TableBody>
                {teamQuery.isLoading ? (
                  <TableSkeletonRows columns={memberTable.getAllLeafColumns().length} />
                ) : memberTable.getRowModel().rows.length > 0 ? (
                  memberTable.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        cell.column.id === "actions" ? (
                          <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                        ) : (
                          <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                        )
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={memberTable.getAllLeafColumns().length}>
                    <EmptyState title={t("console.teams.membersEmpty")} description={t("console.teams.membersEmptyDescription")} />
                  </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
          </TableFrame>
        </PanelSurface>
      </section>
      {editDialogOpen && team ? (
        <TeamInfoDialog
          team={team}
          errorMessage={saveInfoMutation.error ? (saveInfoMutation.error as Error).message : ""}
          isSubmitting={saveInfoMutation.isPending}
          onClose={() => {
            if (!saveInfoMutation.isPending) {
              setEditDialogOpen(false);
            }
          }}
          onSubmit={(payload) => saveInfoMutation.mutate(payload)}
        />
      ) : null}
      {addMemberDialogOpen ? (
        <TeamMemberCreateDialog
          errorMessage={addMemberMutation.error ? (addMemberMutation.error as Error).message : ""}
          isSubmitting={addMemberMutation.isPending}
          onClose={() => {
            if (!addMemberMutation.isPending) {
              setAddMemberDialogOpen(false);
            }
          }}
          onSubmit={(payload) => addMemberMutation.mutate(payload)}
        />
      ) : null}
      {disableConfirmOpen && team ? (
        <Dialog
          title={t("console.teams.disableDialog.title")}
          size="sm"
          onClose={() => {
            if (!statusMutation.isPending) {
              setDisableConfirmOpen(false);
            }
          }}
          closeDisabled={statusMutation.isPending}
          footer={
            <>
              <Button type="button" onClick={() => setDisableConfirmOpen(false)} disabled={statusMutation.isPending}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                loading={statusMutation.isPending}
                disabled={statusMutation.isPending}
                onClick={() => statusMutation.mutate(false)}
              >
                {t("console.teams.disableDialog.confirm")}
              </Button>
            </>
          }
        >
          <div className="grid gap-3">
            <p className="text-body leading-5 text-ink-soft">{t("console.teams.disableDialog.message", { name: team.name })}</p>
          </div>
        </Dialog>
      ) : null}
      {memberPendingRemoval ? (
        <Dialog
          title={t("console.teams.removeMemberTitle")}
          size="sm"
          onClose={() => {
            if (!removeMemberMutation.isPending) {
              setMemberPendingRemoval(null);
            }
          }}
          closeDisabled={removeMemberMutation.isPending}
          footer={
            <>
              <Button type="button" onClick={() => setMemberPendingRemoval(null)} disabled={removeMemberMutation.isPending}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                loading={removeMemberMutation.isPending}
                disabled={removeMemberMutation.isPending}
                onClick={() => removeMemberMutation.mutate(memberPendingRemoval.id)}
              >
                {t("console.teams.confirmRemove")}
              </Button>
            </>
          }
        >
          <div className="grid gap-3">
            <p className="text-body leading-5 text-ink-soft">
              {t("console.teams.removeMemberConfirm", { name: memberPendingRemoval.name || memberPendingRemoval.user_id })}
            </p>
          </div>
        </Dialog>
      ) : null}
    </>
  );
}

function TeamInfoItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

function teamMemberRoleLabel(t: Translator, role: string): string {
  if (role === "leader") {
    return t("console.teams.role.leader");
  }
  if (role === "member") {
    return t("console.teams.role.member");
  }
  return role || "-";
}

function teamMemberTableColumns({
  t,
  disabled,
  onToggleRole,
  onRemove,
}: {
  t: Translator;
  disabled: boolean;
  onToggleRole: (member: TeamMemberItem) => void;
  onRemove: (member: TeamMemberItem) => void;
}): ColumnDef<TeamMemberItem>[] {
  return [
    {
      header: t("console.teams.column.member"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.name || row.original.user_id}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.user_id}</code>
        </div>
      ),
    },
    {
      header: t("console.teams.column.department"),
      cell: ({ row }) => row.original.department || "-",
    },
    {
      header: t("common.role"),
      cell: ({ row }) => (
        <Badge tone={row.original.role === "leader" ? "bond" : "neutral"}>
          {teamMemberRoleLabel(t, row.original.role)}
        </Badge>
      ),
    },
    {
      header: t("console.teams.column.addedAt"),
      cell: ({ row }) => formatDateTime(row.original.added_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" disabled={disabled} onClick={() => onToggleRole(row.original)}>
            {row.original.role === "leader" ? t("console.teams.setMember") : t("console.teams.setLeader")}
          </TableRowActionButton>
          <TableRowActionButton type="button" variant="ghost-danger" disabled={disabled} onClick={() => onRemove(row.original)}>
            {t("common.remove")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
}

function TeamInfoDialog({
  team,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  team: TeamDetail;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TeamInfoFormPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description ?? "");

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
      title={t("console.teams.editTitle")}
      onClose={onClose}
      closeDisabled={isSubmitting}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button form="team-info-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="team-info-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("console.teams.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

function TeamMemberCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TeamMemberCreatePayload) => void;
}) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<TeamMemberRole>("member");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedUserId = userId.trim();
    if (!normalizedUserId) {
      return;
    }
    onSubmit({ user_id: normalizedUserId, role });
  };

  return (
    <Dialog
      title={t("console.teams.addMember")}
      onClose={onClose}
      closeDisabled={isSubmitting}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button form="team-member-create-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="team-member-create-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.user")}>
          <UserSearchInput value={userId} onChange={setUserId} required />
        </Field>
        <Field label={t("common.role")}>
          <SelectInput value={role} onChange={(event) => setRole(event.currentTarget.value as TeamMemberRole)}>
            <option value="member">{t("console.teams.role.member")}</option>
            <option value="leader">{t("console.teams.role.leader")}</option>
          </SelectInput>
        </Field>
        {errorMessage ? <StatusBanner tone="signal" title={t("console.teams.addMemberFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
