import { AlertTriangle } from "lucide-react";

import { Button } from "./Button";
import { Dialog } from "./Dialog";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "确认",
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel}>取消</Button>
          <Button variant="danger" icon={<AlertTriangle size={16} />} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p>{message}</p>
    </Dialog>
  );
}
