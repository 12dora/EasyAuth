import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { API_SESSION_EXPIRED_EVENT } from "../../lib/api";
import {
  IDENTITY_CHECK_INTERVAL_MS,
  IDENTITY_CHECK_MESSAGE_TYPE,
  IDENTITY_CHECK_TIMEOUT_MS,
  IDENTITY_CHECK_URL,
  IDENTITY_CHECK_VISIBLE_THROTTLE_MS,
} from "../../lib/upstreamIdentityCheck";
import type { IdentityCheckOutcome } from "../../lib/upstreamIdentityCheck";
import { IDENTITY_CHECK_FRAME_TEST_ID, useUpstreamIdentityCheck } from "./useUpstreamIdentityCheck";

function frames(): HTMLIFrameElement[] {
  return Array.from(document.querySelectorAll<HTMLIFrameElement>(`iframe[data-testid="${IDENTITY_CHECK_FRAME_TEST_ID}"]`));
}

function postOutcome(outcome: IdentityCheckOutcome, origin = window.location.origin): void {
  act(() => {
    window.dispatchEvent(
      new MessageEvent("message", { data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome }, origin }),
    );
  });
}

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: state });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function renderCheck(enabled = true) {
  const navigator = { reload: vi.fn(), assign: vi.fn() };
  const onSessionExpiredNotice = vi.fn();
  const view = renderHook(() => useUpstreamIdentityCheck({ enabled, navigator, onSessionExpiredNotice }));
  return { ...view, navigator, onSessionExpiredNotice };
}

describe("useUpstreamIdentityCheck", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.history.pushState({}, "", "/portal/requests?tab=pending");
  });

  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  });

  test("本地管理员会话不复核, 不挂 iframe", () => {
    renderCheck(false);

    expect(frames()).toHaveLength(0);
  });

  test("挂载即发起一次复核: 隐藏 iframe 指向静默登录且不可聚焦", () => {
    renderCheck();

    const [frame] = frames();
    expect(frame).toBeDefined();
    expect(frame.getAttribute("src")).toBe(IDENTITY_CHECK_URL);
    expect(frame.getAttribute("aria-hidden")).toBe("true");
    expect(frame.tabIndex).toBe(-1);
    expect(frame.hidden).toBe(true);
  });

  test("身份未变时收掉 iframe 且不做任何跳转", () => {
    const { navigator, onSessionExpiredNotice } = renderCheck();

    postOutcome("unchanged");

    expect(frames()).toHaveLength(0);
    expect(navigator.reload).not.toHaveBeenCalled();
    expect(navigator.assign).not.toHaveBeenCalled();
    expect(onSessionExpiredNotice).not.toHaveBeenCalled();
  });

  test("上游换人时整页重载", () => {
    const { navigator } = renderCheck();

    postOutcome("changed");

    expect(navigator.reload).toHaveBeenCalledTimes(1);
    expect(frames()).toHaveLength(0);
  });

  test("上游已登出时跳登录页并带上当前地址", () => {
    const { navigator } = renderCheck();

    postOutcome("logged_out");

    expect(navigator.assign).toHaveBeenCalledWith("/auth/sign-in/?next=%2Fportal%2Frequests%3Ftab%3Dpending");
  });

  test("跨源消息不被采信", () => {
    const { navigator } = renderCheck();

    postOutcome("logged_out", "https://evil.example.test");

    expect(navigator.assign).not.toHaveBeenCalled();
    expect(frames()).toHaveLength(1);
  });

  test("启动复核失败时不打扰用户, 只收掉 iframe", () => {
    const { onSessionExpiredNotice, navigator } = renderCheck();

    postOutcome("error");

    expect(frames()).toHaveLength(0);
    expect(onSessionExpiredNotice).not.toHaveBeenCalled();
    expect(navigator.reload).not.toHaveBeenCalled();
  });

  test("15 秒没有结论按失败收尾", () => {
    renderCheck();

    act(() => {
      vi.advanceTimersByTime(IDENTITY_CHECK_TIMEOUT_MS);
    });

    expect(frames()).toHaveLength(0);
  });

  test("401 触发的复核失败时才落回登录失效提示", () => {
    const { onSessionExpiredNotice } = renderCheck();
    postOutcome("unchanged");

    act(() => {
      window.dispatchEvent(new CustomEvent(API_SESSION_EXPIRED_EVENT));
    });
    expect(frames()).toHaveLength(1);
    expect(onSessionExpiredNotice).not.toHaveBeenCalled();

    postOutcome("error");

    expect(onSessionExpiredNotice).toHaveBeenCalledTimes(1);
  });

  test("401 撞上在途复核时结论按 401 口径落地", () => {
    const { onSessionExpiredNotice } = renderCheck();

    act(() => {
      window.dispatchEvent(new CustomEvent(API_SESSION_EXPIRED_EVENT));
    });
    // 启动那次复核还在途, 不会再挂第二个 iframe。
    expect(frames()).toHaveLength(1);

    postOutcome("error");

    expect(onSessionExpiredNotice).toHaveBeenCalledTimes(1);
  });

  test("回到前台 60 秒内不重复复核, 超过窗口才再来一次", () => {
    renderCheck();
    postOutcome("unchanged");

    setVisibility("hidden");
    setVisibility("visible");
    expect(frames()).toHaveLength(0);

    act(() => {
      vi.advanceTimersByTime(IDENTITY_CHECK_VISIBLE_THROTTLE_MS);
    });
    setVisibility("visible");

    expect(frames()).toHaveLength(1);
  });

  test("页面可见时每 5 分钟复核一次", () => {
    renderCheck();
    postOutcome("unchanged");

    act(() => {
      vi.advanceTimersByTime(IDENTITY_CHECK_INTERVAL_MS);
    });

    expect(frames()).toHaveLength(1);
  });

  test("标签页在后台时不做轮询复核", () => {
    renderCheck();
    postOutcome("unchanged");
    setVisibility("hidden");

    act(() => {
      vi.advanceTimersByTime(IDENTITY_CHECK_INTERVAL_MS);
    });

    expect(frames()).toHaveLength(0);
  });

  test("卸载时收掉 iframe 与监听", () => {
    const { unmount, navigator } = renderCheck();

    unmount();
    expect(frames()).toHaveLength(0);

    postOutcome("changed");
    expect(navigator.reload).not.toHaveBeenCalled();
  });
});
