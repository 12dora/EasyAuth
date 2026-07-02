import { Copy } from "lucide-react";

import { Button } from "./Button";

interface CodeBlockProps {
  code: string;
  language?: string;
}

export function CodeBlock({ code, language }: CodeBlockProps) {
  return (
    <div className="overflow-hidden rounded-[3px] border border-[rgb(var(--hairline-strong))] bg-ink text-paper">
      <div className="flex h-10 items-center justify-between border-b border-white/10 bg-white/5 px-3">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-white/65">{language ?? "text"}</span>
        <Button
          variant="ghost"
          size="sm"
          icon={<Copy size={14} />}
          onClick={() => void navigator.clipboard?.writeText(code)}
          aria-label="复制"
          className="text-white/75 hover:bg-white/10 hover:text-white"
        />
      </div>
      <pre className="max-h-80 overflow-auto p-4 text-sm leading-6">
        <code className="font-mono text-paper">{code}</code>
      </pre>
    </div>
  );
}
