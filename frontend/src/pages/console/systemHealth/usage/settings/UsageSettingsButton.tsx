import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../../components/Button";
import { useI18n } from "../../../../../i18n/I18nProvider";
import { UsageSettingsDialog } from "./UsageSettingsDialog";

/**
 * 打开用量设置弹窗的入口。
 * primary: 页签右上角的主按钮; inline: 配额卡片里「还没设配额」的就地入口。
 */
export default function UsageSettingsButton({ variant = "primary" }: { variant?: "primary" | "inline" }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const inline = variant === "inline";

  return (
    <>
      <Button
        type="button"
        variant={inline ? "ghost" : "primary"}
        size={inline ? "sm" : "md"}
        icon={<SlidersHorizontal size={inline ? 14 : 16} />}
        onClick={() => setOpen(true)}
      >
        {t(inline ? "usageSettings.openInline" : "usageSettings.open")}
      </Button>
      {open ? <UsageSettingsDialog onClose={() => setOpen(false)} /> : null}
    </>
  );
}
