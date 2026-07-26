import { afterEach, describe, expect, test, vi } from "vitest";

import { checkBrowserSupport } from "./browserSupport";

describe("checkBrowserSupport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("支持现代浏览器基线能力", () => {
    vi.stubGlobal("ResizeObserver", class ResizeObserver {
      observe() {}
      disconnect() {}
    });
    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000000" });

    expect(checkBrowserSupport()).toEqual({ supported: true, missing: [] });
  });

  test("缺失平台能力时快速报告不支持, 不进入静默 fallback", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    vi.stubGlobal("crypto", {});

    const result = checkBrowserSupport();

    expect(result.supported).toBe(false);
    expect(result.missing).toContain("ResizeObserver");
    expect(result.missing).toContain("crypto.randomUUID");
  });
});
