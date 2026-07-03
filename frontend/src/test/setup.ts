import "@testing-library/jest-dom/vitest";

// jsdom 不实现 ResizeObserver; 侧边栏指示灯等布局测量逻辑依赖它。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}
