import { Copy } from "lucide-react";

import { Button } from "./Button";

interface CodeBlockProps {
  code: string;
  language?: string;
}

export function CodeBlock({ code, language }: CodeBlockProps) {
  return (
    <div className="code-block">
      <div className="code-block-header">
        <span>{language ?? "text"}</span>
        <Button
          variant="ghost"
          icon={<Copy size={14} />}
          onClick={() => void navigator.clipboard?.writeText(code)}
          aria-label="复制"
        />
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
