import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { apiRequest } from "../../../../lib/api";
import type { StructuredQueryTestResult } from "./queryTestModel";

/**
 * 权限查询试验的表单状态与提交。
 * latestRequestRef 用于丢弃过期响应: 只有最后一次提交的结果会写入 result。
 */
export function useQueryTest(appKey: string) {
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<StructuredQueryTestResult | null>(null);
  const latestRequestRef = useRef(0);
  const testMutation = useMutation({
    mutationFn: ({ requestId, snapshot }: { requestId: number; snapshot: { userId: string; token: string } }) =>
      apiRequest<StructuredQueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: snapshot.userId, token: snapshot.token },
      }).then((payload) => ({ payload, requestId })),
    onSuccess: ({ payload, requestId }) => {
      if (requestId !== latestRequestRef.current) {
        return;
      }
      setResult(payload);
      setToken("");
    },
  });
  const submit = () => {
    latestRequestRef.current += 1;
    testMutation.mutate({
      requestId: latestRequestRef.current,
      snapshot: { userId: userId.trim(), token },
    });
  };

  return { userId, setUserId, token, setToken, result, testMutation, submit };
}
