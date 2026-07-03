import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

// jsdom 不实现 ResizeObserver; 侧边栏指示灯等布局测量逻辑依赖它。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom 在 about:blank 下不提供 localStorage; I18nProvider 的语言持久化依赖它。
if (typeof window !== "undefined" && !window.localStorage) {
  const store = new Map<string, string>();
  const localStorageStub: Pick<Storage, "getItem" | "setItem" | "removeItem" | "clear"> = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  };
  Object.defineProperty(window, "localStorage", { value: localStorageStub });
}

// 语言偏好等持久化状态不得在用例间泄漏。
beforeEach(() => {
  window.localStorage.clear();
});
