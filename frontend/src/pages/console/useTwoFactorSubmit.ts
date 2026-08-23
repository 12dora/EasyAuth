import { useState } from "react";

/**
 * 两步验证各弹窗共用的提交壳: 提交中再次点击直接忽略, 失败时把错误交给调用方的 mapError 翻译成文案。
 * 错误只展示不吞: mapError 必须返回给用户看的具体原因。
 */
export function useTwoFactorSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async (action: () => Promise<void>, mapError: (caught: unknown) => string) => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (caught) {
      setError(mapError(caught));
    } finally {
      setBusy(false);
    }
  };

  return { busy, error, setError, run };
}
