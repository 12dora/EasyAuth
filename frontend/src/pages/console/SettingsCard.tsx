import type { FormEvent, HTMLAttributes, ReactNode } from "react";

import { Badge } from "../../components/Badge";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { cn } from "../../lib/cn";
import type { BadgeTone } from "../../lib/status";

export interface SettingsCardStatus {
  tone: BadgeTone;
  label: string;
}

interface SettingsCardProps extends Omit<HTMLAttributes<HTMLElement>, "title" | "onSubmit"> {
  /** 小标签(身份 / 钉钉 / 安全), 供一屏内快速分组。 */
  eyebrow: string;
  title: string;
  description: string;
  status?: SettingsCardStatus;
  titleTestId?: string;
  /** 底部操作区; 固定贴卡片底部, 右对齐。 */
  footer?: ReactNode;
  /** 传入即把卡片主体包成 <form>, 使每张卡自带一次保存提交。 */
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  children: ReactNode;
}

/**
 * 设置页唯一的卡片外框: h-full + flex-col 让同一行的卡片在 grid 上等高,
 * 高度差只体现在主体, 底部操作区靠 mt-auto 始终贴底。
 */
export function SettingsCard({
  eyebrow,
  title,
  description,
  status,
  titleTestId,
  footer,
  onSubmit,
  className,
  children,
  ...props
}: SettingsCardProps) {
  const body = (
    <>
      <div className="flex flex-1 flex-col gap-4">{children}</div>
      {footer ? (
        <div className="mt-auto flex flex-wrap items-center justify-end gap-2 border-t border-ink/10 pt-4">
          {footer}
        </div>
      ) : null}
    </>
  );

  return (
    <PanelSurface padding="lg" className={cn("flex h-full flex-col gap-5", className)} {...props}>
      <header className="space-y-1.5">
        <div className="flex items-start justify-between gap-3">
          <p className="text-label font-semibold uppercase tracking-caps text-accent">{eyebrow}</p>
          {status ? <Badge tone={status.tone}>{status.label}</Badge> : null}
        </div>
        <h2 className="text-base font-semibold leading-tight text-ink" data-test-id={titleTestId}>
          {title}
        </h2>
        <p className="text-body leading-5 text-ink-soft">{description}</p>
      </header>
      {onSubmit ? (
        <form className="flex flex-1 flex-col gap-5" onSubmit={onSubmit}>
          {body}
        </form>
      ) : (
        <div className="flex flex-1 flex-col gap-5">{body}</div>
      )}
    </PanelSurface>
  );
}

/** 卡片内的分隔子块: 只用分隔线 + h3, 不再嵌套卡片。 */
export function SettingsSubBlock({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-3 border-t border-ink/10 pt-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <p className="text-xs leading-5 text-ink-faint">{hint}</p>
      </div>
      {children}
    </div>
  );
}

/** 与控制台其它开关一致: 原生 checkbox + role="switch", 标签在左、开关在右。 */
export function SettingsToggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex items-center justify-between gap-3 text-body text-ink">
        <span className="font-medium">{label}</span>
        <input
          className="size-4 shrink-0 accent-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent/50"
          type="checkbox"
          role="switch"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.checked)}
        />
      </label>
      <p className="text-xs leading-5 text-ink-faint">{hint}</p>
    </div>
  );
}

/** 写入型密钥的状态徽标: 只展示是否已设置, 永不回显密文。 */
export function SecretBadge({
  configured,
  configuredLabel,
  missingLabel,
}: {
  configured: boolean;
  configuredLabel: string;
  missingLabel: string;
}) {
  return <Badge tone={configured ? "evergreen" : "amber"}>{configured ? configuredLabel : missingLabel}</Badge>;
}
