import { useMutation } from "@tanstack/react-query";
import { PlugZap } from "lucide-react";

import { Button } from "../../components/Button";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, type JsonObject } from "../../lib/api";
import { cn } from "../../lib/cn";
import type { Translator } from "../../lib/status";
import type { ConnectionTestResult } from "./consoleSettingsModel";

interface ConnectionTestControlProps {
  /** 该卡片对应的探针端点。 */
  url: string;
  /** 提交时读取表单当前值(含未保存草稿); secret 留空表示沿用落库值。 */
  body: () => JsonObject;
  disabled: boolean;
  /** 按钮的 test id; 结果行用 `${testId}-result`。 */
  testId: string;
}

/**
 * 三张集成卡片共用的「测试连接」控件, 渲染在卡片底部操作区:
 * 结果贴左(mr-auto)、按钮贴右。结果就地展示而不是弹 toast——
 * 连通性是这张卡片自身的状态, 离开卡片就失去语境。
 */
export function ConnectionTestControl({ url, body, disabled, testId }: ConnectionTestControlProps) {
  const { t } = useI18n();
  const testMutation = useMutation({
    mutationFn: (payload: JsonObject) =>
      apiRequest<ConnectionTestResult>(url, { method: "POST", body: payload }),
  });
  const outcome = testOutcome(t, testMutation.data, testMutation.error);

  return (
    <>
      {/* 常驻的 live region: 空态也保留节点, 否则结果到达时读屏不会播报。 */}
      <p
        className={cn("mr-auto text-xs leading-5", outcome?.ok ? "text-ink-soft" : "text-signal")}
        role="status"
        data-test-id={`${testId}-result`}
      >
        {outcome?.text ?? ""}
      </p>
      <Button
        type="button"
        icon={<PlugZap size={15} />}
        loading={testMutation.isPending}
        disabled={disabled}
        data-test-id={testId}
        onClick={() => testMutation.mutate(body())}
      >
        {t("settings.connectionTest.action")}
      </Button>
    </>
  );
}

interface TestOutcome {
  ok: boolean;
  text: string;
}

/** 传输层失败与后端判定失败对管理员是同一件事: 都渲染成「连接失败：{原因}」。 */
function testOutcome(
  t: Translator,
  result: ConnectionTestResult | undefined,
  error: Error | null,
): TestOutcome | null {
  if (error) {
    return { ok: false, text: t("settings.connectionTest.failed", { message: error.message }) };
  }
  if (!result) {
    return null;
  }
  if (result.ok) {
    return { ok: true, text: t("settings.connectionTest.success", { ms: result.latency_ms }) };
  }
  return {
    ok: false,
    text: t("settings.connectionTest.failed", { message: result.error_message }),
  };
}
