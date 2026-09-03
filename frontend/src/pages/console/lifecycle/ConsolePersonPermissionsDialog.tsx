import { useState, type FormEvent } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { PersonRow } from "../../../lib/domain";

/**
 * 人员权限弹窗。当前唯一可配置项是「是否管理员」——它就是门户右上角
 * 「管理后台」入口的开关, 因此这里只有一个布尔控件, 不做成通用权限编辑器。
 */
export function ConsolePersonPermissionsDialog({
  person,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  person: PersonRow;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (isConsoleAdmin: boolean) => void;
}) {
  const { t } = useI18n();
  // 初值取列表行的当前值; 保存后的真相由列表刷新给出, 这里不做本地乐观改写。
  const [isConsoleAdmin, setIsConsoleAdmin] = useState(person.is_console_admin);
  const personName = person.name || person.user_id;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit(isConsoleAdmin);
  };

  return (
    <Dialog
      title={t("people.permissionsDialog.title")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            form="person-permissions-form"
            type="submit"
            variant="primary"
            loading={isSubmitting}
            disabled={isSubmitting}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="person-permissions-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">
          {t("people.permissionsDialog.message", { name: personName })}
        </p>
        {/* 复选框自带可见 label, 因此外层 Field 用 as="group": 不再往控件上注入 htmlFor/id。 */}
        <Field
          label={t("people.permissionsDialog.consoleAdmin")}
          hint={t("people.permissionsDialog.consoleAdminHint")}
          as="group"
        >
          <label className="inline-flex items-center gap-2 text-body text-ink">
            <input
              type="checkbox"
              checked={isConsoleAdmin}
              disabled={isSubmitting}
              onChange={(event) => setIsConsoleAdmin(event.currentTarget.checked)}
            />
            <span>{t("people.permissionsDialog.consoleAdminCheckbox")}</span>
          </label>
        </Field>
        {errorMessage ? (
          <StatusBanner live="alert" tone="signal" title={t("people.permissionsDialog.failed")} message={errorMessage} />
        ) : null}
      </form>
    </Dialog>
  );
}
