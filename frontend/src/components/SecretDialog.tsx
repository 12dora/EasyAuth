import { ShieldCheck } from "lucide-react";

import { Button } from "./Button";
import { CodeBlock } from "./CodeBlock";
import { Dialog } from "./Dialog";

interface SecretDialogProps {
  title: string;
  primaryLabel: string;
  primaryValue: string;
  secondaryLabel?: string;
  secondaryValue?: string;
  onClose: () => void;
}

export function SecretDialog({
  title,
  primaryLabel,
  primaryValue,
  secondaryLabel,
  secondaryValue,
  onClose,
}: SecretDialogProps) {
  return (
    <Dialog
      title={title}
      onClose={onClose}
      footer={
        <Button variant="primary" icon={<ShieldCheck size={16} />} onClick={onClose}>
          关闭
        </Button>
      }
    >
      <div className="mb-4 rounded-[3px] border border-amber/30 bg-amber/8 px-4 py-3 text-sm leading-6 text-ink">
        明文凭据仅本次展示。关闭后前端会清除该值，后续只能重新创建或轮换。
      </div>
      <div className="space-y-4">
        <CodeBlock language={primaryLabel} code={primaryValue} />
        {secondaryLabel && secondaryValue ? <CodeBlock language={secondaryLabel} code={secondaryValue} /> : null}
      </div>
    </Dialog>
  );
}
