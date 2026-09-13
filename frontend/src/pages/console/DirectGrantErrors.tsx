import { ApiError } from "../../lib/api";
import type { JsonValue } from "../../lib/api";

export function ErrorList({ messages }: { messages: string[] }) {
  if (messages.length === 0) {
    return null;
  }
  return (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-signal">
      {messages.map((message) => (
        <li key={message}>{message}</li>
      ))}
    </ul>
  );
}

/** 后端 422 语义校验把逐条中文原因放在 details.errors 里; 不是这个形状就不猜, 只展示主消息。 */
export function detailErrorMessages(error: Error | null): string[] {
  if (!(error instanceof ApiError)) {
    return [];
  }
  const details: JsonValue | undefined = error.details;
  if (typeof details !== "object" || details === null || Array.isArray(details)) {
    return [];
  }
  const errors = details.errors;
  if (!Array.isArray(errors)) {
    return [];
  }
  return errors.filter((item): item is string => typeof item === "string");
}
