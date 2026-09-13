import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test, vi } from "vitest";

import { MutationErrorBanner } from "../components/StatusBanner";
import { useApiMutation } from "./query";

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("MutationErrorBanner", () => {
  test("无错误不渲染, 有 Error 或字符串时展示 signal 横幅", () => {
    const { rerender } = render(<MutationErrorBanner title="保存失败" error={null} />);
    expect(screen.queryByRole("alert")).toBeNull();

    rerender(<MutationErrorBanner title="保存失败" error={new Error("应用不存在")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("保存失败");
    expect(screen.getByRole("alert")).toHaveTextContent("应用不存在");

    rerender(<MutationErrorBanner title="保存失败" error="" />);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("useApiMutation", () => {
  test("成功后按 queryKey 失效缓存并调用 onSuccess", async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const onSuccess = vi.fn();
    const { result } = renderHook(
      () =>
        useApiMutation({
          mutationFn: async (name: string) => ({ name }),
          invalidateQueryKeys: [["console", "apps"]],
          onSuccess,
        }),
      { wrapper: wrapperFor(client) },
    );

    result.current.mutate("crm");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(onSuccess).toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["console", "apps"] });
  });
});
