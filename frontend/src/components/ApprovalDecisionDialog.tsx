import { useState, type FormEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { Field, TextArea } from "./Field";
import { StatusBanner } from "./StatusBanner";

export type ApprovalDecisionMode = "approve" | "reject";

interface ApprovalDecisionDialogProps {
  mode: ApprovalDecisionMode;
  /** 弹窗正文里对被处理申请的描述(申请人/应用等数据文案)。 */
  description: string;
  /** 可选说明行, 如控制台代审的审计提示。 */
  note?: string;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (comment: string) => void;
}

/** 同意/驳回共用的审批意见弹窗: 驳回时意见必填(前端校验), 服务端 422 由 errorMessage 兜底展示。 */
export function ApprovalDecisionDialog({
  mode,
  description,
  note,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: ApprovalDecisionDialogProps) {
  const { t } = useI18n();
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState("");
  const isReject = mode === "reject";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedComment = comment.trim();
    if (isReject && !normalizedComment) {
      setCommentError(t("approvals.commentRequired"));
      return;
    }
    onSubmit(normalizedComment);
  };

  return (
    <Dialog
      title={isReject ? t("approvals.rejectTitle") : t("approvals.approveTitle")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            form="approval-decision-form"
            type="submit"
            variant={isReject ? "danger" : "primary"}
            loading={isSubmitting}
            disabled={isSubmitting}
          >
            {isReject ? t("approvals.rejectConfirm") : t("approvals.approveConfirm")}
          </Button>
        </>
      }
    >
      <form id="approval-decision-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{description}</p>
        <Field
          label={t("approvals.comment")}
          hint={isReject ? t("approvals.commentRequiredHint") : t("approvals.commentOptionalHint")}
          error={commentError}
        >
          <TextArea
            rows={3}
            value={comment}
            onChange={(event) => {
              setComment(event.currentTarget.value);
              if (commentError) {
                setCommentError("");
              }
            }}
          />
        </Field>
        {note ? <p className="text-xs leading-5 text-ink-faint">{note}</p> : null}
        {errorMessage ? (
          <StatusBanner
            tone="signal"
            title={isReject ? t("approvals.rejectFailed") : t("approvals.approveFailed")}
            message={errorMessage}
          />
        ) : null}
      </form>
    </Dialog>
  );
}
