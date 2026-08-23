/** 渲染目录实体的新建与编辑表单弹窗。 */

import type { Dispatch, FormEvent, SetStateAction } from "react";

import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { PermissionGroupItem } from "../../../../lib/domain";
import type { PermissionForm, PermissionGroupForm, ScopeForm } from "./catalogModel";

type MutationState = {
  isPending: boolean;
  error: Error | null;
  mutate: () => void;
};

export function ScopeDialog({ form, editingKey, mutation, onChange, onClose }: {
  form: ScopeForm;
  editingKey: string;
  mutation: MutationState;
  onChange: Dispatch<SetStateAction<ScopeForm>>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog title={editingKey ? t("console.catalog.scope.editTitle") : t("console.catalog.scope.createTitle")} onClose={onClose} footer={
      <>
        <Button type="button" onClick={onClose}>{t("common.cancel")}</Button>
        <Button form="scope-form" type="submit" variant="primary" loading={mutation.isPending} disabled={mutation.isPending}>{t("common.save")}</Button>
      </>
    }>
      <form id="scope-form" className="grid gap-4" onSubmit={(event) => submit(event, mutation.mutate)}>
        <Field label={t("console.catalog.scope.column.key")}>
          <TextInput value={form.key} onChange={(event) => onChange((current) => ({ ...current, key: event.currentTarget.value }))} required />
        </Field>
        <Field label={t("common.name")}>
          <TextInput value={form.name} onChange={(event) => onChange((current) => ({ ...current, name: event.currentTarget.value }))} required />
        </Field>
        <Field label={t("common.description")}>
          <TextArea value={form.description} onChange={(event) => onChange((current) => ({ ...current, description: event.currentTarget.value }))} />
        </Field>
        {mutation.error ? <StatusBanner live="alert" tone="signal" title={t("console.catalog.scopeSaveFailed")} message={mutation.error.message} /> : null}
      </form>
    </Dialog>
  );
}

export function GroupDialog({ form, groups, editingKey, mutation, onChange, onClose }: {
  form: PermissionGroupForm;
  groups: PermissionGroupItem[];
  editingKey: string;
  mutation: MutationState;
  onChange: Dispatch<SetStateAction<PermissionGroupForm>>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog title={editingKey ? t("console.catalog.group.editTitle") : t("console.catalog.group.createTitle")} onClose={onClose} footer={
      <>
        <Button type="button" onClick={onClose}>{t("common.cancel")}</Button>
        <Button form="group-form" type="submit" variant="primary" loading={mutation.isPending} disabled={mutation.isPending || !form.key || !form.name}>{t("common.save")}</Button>
      </>
    }>
      <form id="group-form" className="grid gap-4" onSubmit={(event) => submit(event, mutation.mutate)}>
        <Field label={t("console.catalog.group.column.key")}>
          <TextInput value={form.key} onChange={(event) => onChange((current) => ({ ...current, key: event.currentTarget.value }))} required />
        </Field>
        <Field label={t("common.name")}>
          <TextInput value={form.name} onChange={(event) => onChange((current) => ({ ...current, name: event.currentTarget.value }))} required />
        </Field>
        <Field label={t("console.catalog.group.parent")}>
          <SelectInput value={form.parent_key} onChange={(event) => onChange((current) => ({ ...current, parent_key: event.currentTarget.value }))}>
            <option value="">{t("console.catalog.group.parentNone")}</option>
            {groups.filter((group) => group.key !== form.key).map((group) => (
              <option key={group.key} value={group.key}>{group.name} ({group.key})</option>
            ))}
          </SelectInput>
        </Field>
        <Field label={t("common.description")}>
          <TextArea value={form.description} onChange={(event) => onChange((current) => ({ ...current, description: event.currentTarget.value }))} />
        </Field>
        {mutation.error ? <StatusBanner live="alert" tone="signal" title={t("console.catalog.groupSaveFailed")} message={mutation.error.message} /> : null}
      </form>
    </Dialog>
  );
}

export function PermissionDialog({ form, groups, editingKey, mutation, onChange, onClose }: {
  form: PermissionForm;
  groups: PermissionGroupItem[];
  editingKey: string;
  mutation: MutationState;
  onChange: Dispatch<SetStateAction<PermissionForm>>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog title={editingKey ? t("console.catalog.permission.editTitle") : t("console.catalog.permission.createTitle")} onClose={onClose} size="lg" footer={
      <>
        <Button type="button" onClick={onClose}>{t("common.cancel")}</Button>
        <Button form="permission-form" type="submit" variant="primary" loading={mutation.isPending} disabled={mutation.isPending}>{t("common.save")}</Button>
      </>
    }>
      <form id="permission-form" className="grid gap-4 md:grid-cols-2" onSubmit={(event) => submit(event, mutation.mutate)}>
        <Field label={t("console.catalog.permission.column.key")}>
          <TextInput value={form.key} onChange={(event) => onChange((current) => ({ ...current, key: event.currentTarget.value }))} required />
        </Field>
        <Field label={t("common.name")}>
          <TextInput value={form.name} onChange={(event) => onChange((current) => ({ ...current, name: event.currentTarget.value }))} required />
        </Field>
        <Field label={t("console.catalog.permission.column.group")}>
          <SelectInput value={form.group_key} onChange={(event) => onChange((current) => ({ ...current, group_key: event.currentTarget.value }))}>
            <option value="">{t("console.catalog.permission.groupNone")}</option>
            {groups.map((group) => (
              <option key={group.key} value={group.key}>{group.name} ({group.key})</option>
            ))}
          </SelectInput>
        </Field>
        <Field label={t("console.catalog.permission.column.scopes")} hint={t("console.catalog.permission.scopesHint")}>
          <TextInput value={form.supported_scopes} onChange={(event) => onChange((current) => ({ ...current, supported_scopes: event.currentTarget.value }))} />
        </Field>
        <Field label={t("console.catalog.permission.column.risk")}>
          <SelectInput value={form.risk_level} onChange={(event) => onChange((current) => ({ ...current, risk_level: event.currentTarget.value }))}>
            <option value="standard">{t("console.catalog.risk.standard")}</option>
            <option value="high">{t("console.catalog.risk.high")}</option>
          </SelectInput>
        </Field>
        <Field label={t("common.description")}>
          <TextArea value={form.description} onChange={(event) => onChange((current) => ({ ...current, description: event.currentTarget.value }))} />
        </Field>
        {mutation.error ? <StatusBanner live="alert" tone="signal" title={t("console.catalog.permissionSaveFailed")} message={mutation.error.message} /> : null}
      </form>
    </Dialog>
  );
}

function submit(event: FormEvent<HTMLFormElement>, action: () => void) {
  event.preventDefault();
  action();
}
