import { useEffect, useRef } from "react";

import { API_SESSION_EXPIRED_EVENT } from "../../lib/api";
import { signInUrlForCurrentPage } from "../../lib/signInUrl";
import {
  IDENTITY_CHECK_ERROR_RESULT,
  IDENTITY_CHECK_INTERVAL_MS,
  IDENTITY_CHECK_TIMEOUT_MS,
  IDENTITY_CHECK_URL,
  INITIAL_IDENTITY_CHECK_STATE,
  completeIdentityCheck,
  identityCheckResultFromMessage,
  requestIdentityCheck,
} from "../../lib/upstreamIdentityCheck";
import type {
  IdentityCheckAction,
  IdentityCheckResult,
  IdentityCheckState,
  IdentityCheckTrigger,
} from "../../lib/upstreamIdentityCheck";

/** 隐藏 iframe 的标记, 供壳层测试与排查时定位。 */
export const IDENTITY_CHECK_FRAME_TEST_ID = "upstream-identity-check-frame";

/**
 * 整页跳转能力。抽成参数只为可测:
 * jsdom 里 `window.location.reload/assign` 会直接抛 Not implemented, 没法断言。
 */
export interface PageNavigator {
  reload: () => void;
  assign: (url: string) => void;
}

export const browserPageNavigator: PageNavigator = {
  reload: () => {
    window.location.reload();
  },
  assign: (url: string) => {
    window.location.assign(url);
  },
};

export interface UpstreamIdentityCheckOptions {
  /** 只有 Authentik 建立的会话才复核; 本地管理员会话没有上游, 必须整体跳过。 */
  enabled: boolean;
  /** 本标签页正在显示的上游(Authentik)用户 id; 用来和结论里的身份对账(见 IdentityCheckResult)。 */
  currentUserId: string;
  /** 复核自身失败(含超时)且这次是 401 触发时调用, 由壳层落回既有的登录失效提示。 */
  onSessionExpiredNotice: () => void;
  navigator?: PageNavigator;
}

/**
 * 上游身份静默复核。
 *
 * 在启动、标签页回到前台(60 秒节流)、可见时每 5 分钟、以及 API 返回 401 这四种时机,
 * 往隐藏 iframe 里打一次 `/auth/login/?silent=1`, 按回调页 postMessage 的结论
 * 重载页面(上游换人)、跳登录页(上游已登出)或什么都不做。
 * 判定逻辑全在 `lib/upstreamIdentityCheck`, 这里只负责 DOM 与事件接线。
 */
export function useUpstreamIdentityCheck({
  enabled,
  currentUserId,
  onSessionExpiredNotice,
  navigator = browserPageNavigator,
}: UpstreamIdentityCheckOptions): void {
  const noticeRef = useRef(onSessionExpiredNotice);
  const navigatorRef = useRef(navigator);
  noticeRef.current = onSessionExpiredNotice;
  navigatorRef.current = navigator;

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let state: IdentityCheckState = INITIAL_IDENTITY_CHECK_STATE;
    let frame: HTMLIFrameElement | null = null;
    let timeoutId: number | null = null;

    const teardownFrame = () => {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
      frame?.remove();
      frame = null;
    };

    const finish = (result: IdentityCheckResult) => {
      if (state.runningTrigger === null) {
        // 超时收尾之后迟到的那条消息, 丢弃(理由见 completeIdentityCheck 的注释)。
        return;
      }
      const completion = completeIdentityCheck(state, result, Date.now(), currentUserId);
      state = completion.state;
      teardownFrame();
      runAction(completion.action);
    };

    const runAction = (action: IdentityCheckAction) => {
      switch (action) {
        case "reload":
          navigatorRef.current.reload();
          return;
        case "sign_in":
          navigatorRef.current.assign(signInUrlForCurrentPage());
          return;
        case "session_expired_notice":
          noticeRef.current();
          return;
        case "none":
          return;
      }
    };

    const start = (trigger: IdentityCheckTrigger) => {
      const request = requestIdentityCheck(state, trigger, Date.now());
      state = request.state;
      if (!request.start) {
        return;
      }
      frame = document.createElement("iframe");
      frame.src = IDENTITY_CHECK_URL;
      frame.hidden = true;
      frame.tabIndex = -1;
      frame.setAttribute("aria-hidden", "true");
      frame.dataset.testid = IDENTITY_CHECK_FRAME_TEST_ID;
      document.body.append(frame);
      timeoutId = window.setTimeout(() => finish(IDENTITY_CHECK_ERROR_RESULT), IDENTITY_CHECK_TIMEOUT_MS);
    };

    const onMessage = (event: MessageEvent) => {
      // 只认当前这个 iframe 自己发回来的消息: 同源窗口(上一次超时后才回话的旧 iframe、别的 iframe、
      // opener 等)都能往这里 postMessage, 光看 origin 和 type 会把别人的结论当成本次复核的结果。
      if (frame === null || event.source !== frame.contentWindow) {
        return;
      }
      const result = identityCheckResultFromMessage(event, window.location.origin);
      if (result !== null) {
        finish(result);
      }
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        start("visible");
      }
    };
    const onSessionExpired = () => start("session_expired");
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        start("interval");
      }
    }, IDENTITY_CHECK_INTERVAL_MS);

    window.addEventListener("message", onMessage);
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener(API_SESSION_EXPIRED_EVENT, onSessionExpired);
    start("boot");

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("message", onMessage);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener(API_SESSION_EXPIRED_EVENT, onSessionExpired);
      teardownFrame();
    };
  }, [enabled, currentUserId]);
}
