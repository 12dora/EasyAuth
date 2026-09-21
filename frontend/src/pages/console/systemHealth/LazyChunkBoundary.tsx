import { RefreshCcw } from "lucide-react";
import { Component, Suspense, lazy, useCallback, useState } from "react";
import type { ComponentType, ErrorInfo, ReactNode } from "react";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";

export interface LazyChunkBoundaryProps<P extends object> {
  /**
   * 动态 import 工厂, 必须是模块级的稳定引用。
   *
   * 重试时要重新调用它拿一个全新的 lazy 组件: React 把失败的 import promise 记在 lazy 载荷里,
   * 只清错误状态而不换 lazy, 重试会立刻读到同一个已拒绝的 promise, 永远失败。
   */
  loader: () => Promise<{ default: ComponentType<P> }>;
  /** 拿到 chunk 组件后自己决定怎么传 props; 这样 props 类型跟着 loader 走, 不用在边界上再声明一遍。 */
  render: (Chunk: ComponentType<P>) => ReactNode;
  /** chunk 还在下载时的占位。 */
  fallback: ReactNode;
  /** 加载失败横幅的标题。 */
  title: string;
}

interface LazyChunkState<P extends object> {
  attempt: number;
  Component: ComponentType<P>;
}

/**
 * 单个异步 chunk 的本地错误边界。
 *
 * 部署后旧 hash 失效、网络抖动都会让 `import()` 直接抛错。没有本地边界时这个错误一路冒到
 * App.tsx 的路由错误边界, 整个页面(包括另一个页签)都会塌掉, 而"重试"只能整页重载。
 * 这里就地渲染一条横幅 + 重试, 页面其余部分照常工作。
 */
export function LazyChunkBoundary<P extends object>({
  fallback,
  loader,
  render,
  title,
}: LazyChunkBoundaryProps<P>) {
  const [chunk, setChunk] = useState<LazyChunkState<P>>(() => ({ attempt: 0, Component: lazy(loader) }));

  const retry = useCallback(() => {
    setChunk((previous) => ({ attempt: previous.attempt + 1, Component: lazy(loader) }));
  }, [loader]);

  return (
    // attempt 作 key: 换 lazy 的同时把边界自己的错误状态一起丢掉, 不用再写一个复位分支。
    <ChunkErrorBoundary
      key={chunk.attempt}
      renderFallback={(error) => <ChunkLoadFailed error={error} onRetry={retry} title={title} />}
    >
      <Suspense fallback={fallback}>{render(chunk.Component)}</Suspense>
    </ChunkErrorBoundary>
  );
}

interface ChunkErrorBoundaryProps {
  children: ReactNode;
  renderFallback: (error: Error) => ReactNode;
}

interface ChunkErrorBoundaryState {
  error: Error | null;
}

/** 只兜住这一个 chunk 的加载错误: 捕获后不再抛出, 路由级错误边界不会被触发。 */
class ChunkErrorBoundary extends Component<ChunkErrorBoundaryProps, ChunkErrorBoundaryState> {
  state: ChunkErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ChunkErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("EasyAuth lazy chunk failed", error, info.componentStack);
  }

  render(): ReactNode {
    return this.state.error === null ? this.props.children : this.props.renderFallback(this.state.error);
  }
}

function ChunkLoadFailed({ error, onRetry, title }: { error: Error; onRetry: () => void; title: string }) {
  const { t } = useI18n();

  return (
    <div className="space-y-2">
      <StatusBanner live="alert" message={error.message} title={title} tone="signal" />
      <Button icon={<RefreshCcw size={16} />} onClick={onRetry} size="sm">
        {t("common.retry")}
      </Button>
    </div>
  );
}
