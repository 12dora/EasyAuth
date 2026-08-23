import { useState, type FormEvent } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput } from "../../components/UserSelect";
import { useI18n } from "../../i18n/I18nProvider";
import type { TeamDetail, TeamMemberItem } from "../../lib/domain";
import type { TeamInfoFormPayload, TeamMemberCreatePayload, TeamMemberRole } from "./consoleTeamDetailModel";

export function TeamInfoDialog({
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
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.teams.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

export function TeamMemberCreateDialog({
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
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.teams.addMemberFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

export function TeamDisableConfirmDialog({
  team,
  isSubmitting,
  onClose,
  onConfirm,
}: {
  team: TeamDetail;
  isSubmitting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      title={t("console.teams.disableDialog.title")}
      size="sm"
      onClose={onClose}
      closeDisabled={isSubmitting}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button type="button" variant="danger" loading={isSubmitting} disabled={isSubmitting} onClick={onConfirm}>
            {t("console.teams.disableDialog.confirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="text-body leading-5 text-ink-soft">{t("console.teams.disableDialog.message", { name: team.name })}</p>
      </div>
    </Dialog>
  );
}

export function TeamMemberRemoveDialog({
  member,
  isSubmitting,
  onClose,
  onConfirm,
}: {
  member: TeamMemberItem;
  isSubmitting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      title={t("console.teams.removeMemberTitle")}
      size="sm"
      onClose={onClose}
      closeDisabled={isSubmitting}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button type="button" variant="danger" loading={isSubmitting} disabled={isSubmitting} onClick={onConfirm}>
            {t("console.teams.confirmRemove")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="text-body leading-5 text-ink-soft">
          {t("console.teams.removeMemberConfirm", { name: member.name || member.user_id })}
        </p>
      </div>
    </Dialog>
  );
}
