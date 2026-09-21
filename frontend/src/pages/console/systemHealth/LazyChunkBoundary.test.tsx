import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Component } from "react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { LazyChunkBoundary } from "./LazyChunkBoundary";

function LoadedChunk({ label }: { label: string }) {
  return <p>chunk:{label}</p>;
}

/** 站在被测边界外面, 用来断言 chunk 的错误没有继续往上冒(线上那一层是路由错误边界)。 */
class OuterBoundary extends Component<{ children: ReactNode; onCatch: () => void }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onCatch();
  }

  render(): ReactNode {
    return this.state.failed ? <p>outer-boundary-failed</p> : this.props.children;
  }
}

describe("LazyChunkBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("chunk 加载成功时直接渲染, 不出现任何失败横幅", async () => {
    render(
      <LazyChunkBoundary
        fallback={<span>loading</span>}
        loader={async () => ({ default: LoadedChunk })}
        render={(Chunk) => <Chunk label="ok" />}
        title="代码包加载失败"
      />,
    );

    expect(await screen.findByText("chunk:ok")).toBeInTheDocument();
    expect(screen.queryByText("代码包加载失败")).not.toBeInTheDocument();
  });

  test("chunk 加载失败时就地降级, 重试会重新 import 而不是复用失败的 promise", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const onCatch = vi.fn();
    let attempt = 0;
    const loader = vi.fn(async () => {
      attempt += 1;
      if (attempt === 1) {
        throw new Error("Failed to fetch dynamically imported module");
      }
      return { default: LoadedChunk };
    });
    const user = userEvent.setup();

    render(
      <OuterBoundary onCatch={onCatch}>
        <LazyChunkBoundary
          fallback={<span>loading</span>}
          loader={loader}
          render={(Chunk) => <Chunk label="retried" />}
          title="代码包加载失败"
        />
      </OuterBoundary>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("代码包加载失败");
    expect(screen.getByText("Failed to fetch dynamically imported module")).toBeInTheDocument();
    // 关键: 外层边界没被触发, 页面其余部分还在。
    expect(onCatch).not.toHaveBeenCalled();
    expect(screen.queryByText("outer-boundary-failed")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByText("chunk:retried")).toBeInTheDocument();
    expect(loader).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("重试仍然失败时继续停在可重试的失败态", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const loader = vi.fn<() => Promise<{ default: typeof LoadedChunk }>>(async () => {
      throw new Error("chunk 仍不可用");
    });
    const user = userEvent.setup();

    render(
      <LazyChunkBoundary
        fallback={<span>loading</span>}
        loader={loader}
        render={(Chunk) => <Chunk label="never" />}
        title="代码包加载失败"
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("代码包加载失败");
    await user.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("代码包加载失败");
    expect(loader).toHaveBeenCalledTimes(2);
  });
});
