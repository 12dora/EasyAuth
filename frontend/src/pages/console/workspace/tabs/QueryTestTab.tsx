import { useMutation } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { Field, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { Toast } from "../../../../components/Toast";
import { apiRequest } from "../../../../lib/api";
import type { QueryTestResult } from "../../../../lib/domain";

export function QueryTestTab({ appKey }: { appKey: string }) {
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<QueryTestResult | null>(null);
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<QueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: userId, token },
      }),
    onSuccess: (payload) => {
      setResult(payload);
      setToken("");
    },
  });

  return (
    <section className="stack">
      <div className="inline-form">
        <Field label="用户 ID">
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} />
        </Field>
        <Field label="Bearer token">
          <TextInput type="password" value={token} onChange={(event) => setToken(event.currentTarget.value)} autoComplete="off" />
        </Field>
        <Button variant="primary" icon={<Play size={16} />} disabled={!userId || !token} onClick={() => testMutation.mutate()}>
          执行联调
        </Button>
      </div>
      {testMutation.error ? <StatusBanner tone="danger" title="联调失败" message={(testMutation.error as Error).message} /> : null}
      {result ? (
        <>
          <Toast tone="success" message={result.allowed ? "权限查询命中授权" : "查询成功，无授权命中"} />
          <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
        </>
      ) : null}
    </section>
  );
}
