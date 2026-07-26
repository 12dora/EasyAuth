import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { Button } from "./Button";
import { useToast } from "./ui/Toast";

interface CodeBlockProps {
  code: string;
  language?: string;
}

export function CodeBlock({ code, language }: CodeBlockProps) {
  const { t } = useI18n();
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const resetTimeoutRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    return () => window.clearTimeout(resetTimeoutRef.current);
  }, []);

  const copy = async () => {
    if (!navigator.clipboard) {
      setCopied(false);
      toast.error(t("common.copyFailed"));
      return;
    }
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.clearTimeout(resetTimeoutRef.current);
      resetTimeoutRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      toast.error(t("common.copyFailed"));
    }
  };

  return (
    <div className="overflow-hidden rounded-[3px] border border-ink/15 bg-ink text-paper">
      <div className="flex h-10 items-center justify-between border-b border-white/10 bg-white/5 px-3">
        <span className="font-mono text-label font-semibold uppercase tracking-caps text-white/65">{language ?? "text"}</span>
        <Button
          variant="ghost"
          size="sm"
          icon={copied ? <Check size={14} /> : <Copy size={14} />}
          onClick={() => void copy()}
          aria-label={t("common.copy")}
          className="text-white/75 hover:bg-white/10 hover:text-white"
        >
          {copied ? t("common.copied") : null}
        </Button>
      </div>
      <pre className="max-h-80 overflow-auto p-4 text-sm leading-6">
        <code className="font-mono text-paper">{code}</code>
      </pre>
    </div>
  );
}
