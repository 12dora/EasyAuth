import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./Button";

interface DialogProps {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
}

export function Dialog({ title, children, footer, onClose }: DialogProps) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <header className="dialog-header">
          <h2 id="dialog-title">{title}</h2>
          <Button variant="ghost" icon={<X size={16} />} onClick={onClose} aria-label="关闭弹窗" />
        </header>
        <div className="dialog-body">{children}</div>
        {footer ? <footer className="dialog-footer">{footer}</footer> : null}
      </div>
    </div>
  );
}
