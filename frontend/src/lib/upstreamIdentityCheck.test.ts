import { describe, expect, test } from "vitest";

import {
  IDENTITY_CHECK_MESSAGE_TYPE,
  IDENTITY_CHECK_VISIBLE_THROTTLE_MS,
  INITIAL_IDENTITY_CHECK_STATE,
  completeIdentityCheck,
  identityCheckAction,
  identityCheckOutcomeFromMessage,
  requestIdentityCheck,
} from "./upstreamIdentityCheck";
import type { IdentityCheckState } from "./upstreamIdentityCheck";

const ORIGIN = "https://iam.jiefakj.com";

function runningState(trigger: IdentityCheckState["runningTrigger"], lastCompletedAt: number | null = null): IdentityCheckState {
  return { runningTrigger: trigger, lastCompletedAt };
}

describe("requestIdentityCheck", () => {
  test("首次启动直接发起复核", () => {
    const request = requestIdentityCheck(INITIAL_IDENTITY_CHECK_STATE, "boot", 1_000);

    expect(request.start).toBe(true);
    expect(request.state.runningTrigger).toBe("boot");
  });

  test("已有复核在途时后到的触发被合并掉", () => {
    const state = runningState("boot");

    const request = requestIdentityCheck(state, "interval", 1_000);

    expect(request.start).toBe(false);
    expect(request.state).toBe(state);
  });

  test("401 在途时到达会把在途复核升级成 401 触发, 而不是白跑一趟", () => {
    const request = requestIdentityCheck(runningState("interval"), "session_expired", 1_000);

    expect(request.start).toBe(false);
    expect(request.state.runningTrigger).toBe("session_expired");
  });

  test("回到前台时距上次复核不足 60 秒则跳过", () => {
    const state = runningState(null, 1_000);

    const request = requestIdentityCheck(state, "visible", 1_000 + IDENTITY_CHECK_VISIBLE_THROTTLE_MS - 1);

    expect(request.start).toBe(false);
    expect(request.state).toBe(state);
  });

  test("回到前台时距上次复核满 60 秒则复核", () => {
    const request = requestIdentityCheck(
      runningState(null, 1_000),
      "visible",
      1_000 + IDENTITY_CHECK_VISIBLE_THROTTLE_MS,
    );

    expect(request.start).toBe(true);
  });

  test.each(["boot", "interval", "session_expired"] as const)(
    "%s 不受回到前台的节流窗口约束",
    (trigger) => {
      const request = requestIdentityCheck(runningState(null, 1_000), trigger, 1_500);

      expect(request.start).toBe(true);
    },
  );
});

describe("completeIdentityCheck", () => {
  test("收尾后记下完成时间并按触发源给出动作", () => {
    const completion = completeIdentityCheck(runningState("session_expired"), "error", 9_000);

    expect(completion.state).toEqual({ runningTrigger: null, lastCompletedAt: 9_000 });
    expect(completion.action).toBe("session_expired_notice");
  });

  test("超时收尾之后迟到的结论被丢弃, 不再触发任何动作", () => {
    const state = runningState(null, 9_000);

    const completion = completeIdentityCheck(state, "changed", 12_000);

    expect(completion.state).toBe(state);
    expect(completion.action).toBe("none");
  });
});

describe("identityCheckAction", () => {
  test.each(["boot", "visible", "interval", "session_expired"] as const)(
    "上游换人时(%s 触发)整页重载",
    (trigger) => {
      expect(identityCheckAction("changed", trigger)).toBe("reload");
    },
  );

  test.each(["boot", "visible", "interval", "session_expired"] as const)(
    "上游已登出时(%s 触发)跳登录页",
    (trigger) => {
      expect(identityCheckAction("logged_out", trigger)).toBe("sign_in");
    },
  );

  test.each(["boot", "visible", "interval"] as const)("身份未变时(%s 触发)不做任何可见动作", (trigger) => {
    expect(identityCheckAction("unchanged", trigger)).toBe("none");
    expect(identityCheckAction("error", trigger)).toBe("none");
  });

  test("401 触发下身份未变说明本地会话已被静默回调重新建立, 重载即可", () => {
    expect(identityCheckAction("unchanged", "session_expired")).toBe("reload");
  });

  test("401 触发下复核自身失败时才回落到登录失效提示", () => {
    expect(identityCheckAction("error", "session_expired")).toBe("session_expired_notice");
  });
});

describe("identityCheckOutcomeFromMessage", () => {
  test("接受同源的复核结论", () => {
    const outcome = identityCheckOutcomeFromMessage(
      { origin: ORIGIN, data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "changed" } },
      ORIGIN,
    );

    expect(outcome).toBe("changed");
  });

  test.each([
    {
      label: "跨源消息",
      message: { origin: "https://evil.example.test", data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "logged_out" } },
    },
    { label: "别的协议", message: { origin: ORIGIN, data: { type: "webpack:hmr" } } },
    { label: "非对象载荷", message: { origin: ORIGIN, data: "easyauth:identity-check" } },
    { label: "数组载荷", message: { origin: ORIGIN, data: [] } },
  ])("忽略与复核无关的消息: $label", ({ message }) => {
    expect(identityCheckOutcomeFromMessage(message, ORIGIN)).toBeNull();
  });

  test("同源且声明本协议但 outcome 未知时当场抛错", () => {
    expect(() =>
      identityCheckOutcomeFromMessage(
        { origin: ORIGIN, data: { type: IDENTITY_CHECK_MESSAGE_TYPE, outcome: "maybe" } },
        ORIGIN,
      ),
    ).toThrow("身份复核回调给出了未知的 outcome: maybe");
  });
});
