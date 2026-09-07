/**
 * 上游(Authentik)身份静默复核的纯状态机。
 *
 * 背景: Authentik 会话可能在应用毫不知情的情况下结束, 或者换成另一个人登录,
 * 而 EasyAuth 自己的 Django 会话还活着, 页面就会拿着一个过期或错人的身份继续用。
 * 复核动作本身是往隐藏 iframe 里打 `/auth/login/?silent=1`(后端带 prompt=none 走一趟 Authentik),
 * 回调页用 postMessage 回吐结论。这里只放「什么时候该发起」「结论该落成什么动作」的判定,
 * 与 DOM 无关, 便于单测穷举节流、合并与四种结论。
 */

export const IDENTITY_CHECK_URL = "/auth/login/?silent=1";
export const IDENTITY_CHECK_MESSAGE_TYPE = "easyauth:identity-check";
/** 单次复核的上限; 超时按 error 处理, 也就是回到既有的登录失效提示。 */
export const IDENTITY_CHECK_TIMEOUT_MS = 15_000;
/** 页面可见时的轮询间隔。 */
export const IDENTITY_CHECK_INTERVAL_MS = 300_000;
/** 标签页回到前台时的节流窗口: 窗口内刚复核过就不再复核。 */
export const IDENTITY_CHECK_VISIBLE_THROTTLE_MS = 60_000;

const IDENTITY_CHECK_OUTCOMES = ["unchanged", "changed", "logged_out", "error"] as const;

/** 回调页给出的四种结论, 取值由后端契约固定。 */
export type IdentityCheckOutcome = (typeof IDENTITY_CHECK_OUTCOMES)[number];

/** 复核的触发源; 只有 session_expired(API 返回 401) 需要把结论落到用户可见的提示上。 */
export type IdentityCheckTrigger = "boot" | "visible" | "interval" | "session_expired";

/**
 * 结论要执行的动作。
 * - reload: 上游换人后本地会话已切到新身份, 整页重载让所有数据按新身份重取。
 * - sign_in: 上游已登出, 跳到登录页并带上当前地址作为 next。
 * - session_expired_notice: 复核本身失败, 回落到既有的「登录状态已失效」提示。
 * - none: 无需可见变化。
 */
export type IdentityCheckAction = "none" | "reload" | "sign_in" | "session_expired_notice";

export interface IdentityCheckState {
  /** 在途复核的触发源; 没有复核在跑时为 null。 */
  runningTrigger: IdentityCheckTrigger | null;
  /** 上一次复核收尾的时间戳(ms); 供回到前台时节流。 */
  lastCompletedAt: number | null;
}

export const INITIAL_IDENTITY_CHECK_STATE: IdentityCheckState = {
  runningTrigger: null,
  lastCompletedAt: null,
};

export interface IdentityCheckRequest {
  state: IdentityCheckState;
  /** true 表示调用方现在要真的挂起 iframe 发起一次复核。 */
  start: boolean;
}

/**
 * 收到一个触发源时决定是否真的发起复核。
 *
 * 同一时刻只允许一次复核在途: 后到的触发直接丢弃, 不排队(排队只会在网络抖动时堆出一串重复请求)。
 * 唯一的例外是 401: 它必须影响用户可见结果, 所以把在途复核的触发源升级成 session_expired,
 * 让那次复核的结论按 401 的口径落地, 而不是白跑一趟后什么都不做。
 */
export function requestIdentityCheck(
  state: IdentityCheckState,
  trigger: IdentityCheckTrigger,
  now: number,
): IdentityCheckRequest {
  if (state.runningTrigger !== null) {
    if (trigger === "session_expired") {
      return { state: { ...state, runningTrigger: "session_expired" }, start: false };
    }
    return { state, start: false };
  }
  if (trigger === "visible" && isWithinVisibleThrottle(state.lastCompletedAt, now)) {
    return { state, start: false };
  }
  return { state: { ...state, runningTrigger: trigger }, start: true };
}

export interface IdentityCheckCompletion {
  state: IdentityCheckState;
  action: IdentityCheckAction;
}

/**
 * 结论(或超时)到手时收尾。
 *
 * 没有在途复核时说明这是超时收尾之后迟到的那条消息, 只能丢弃:
 * 那次复核已经按 error 落过地了, 再按迟到结论跳转会把用户从当前操作上踢走。
 */
export function completeIdentityCheck(
  state: IdentityCheckState,
  outcome: IdentityCheckOutcome,
  now: number,
): IdentityCheckCompletion {
  const trigger = state.runningTrigger;
  if (trigger === null) {
    return { state, action: "none" };
  }
  return {
    state: { runningTrigger: null, lastCompletedAt: now },
    action: identityCheckAction(outcome, trigger),
  };
}

/**
 * 结论到动作的映射。
 *
 * unchanged 在 401 触发下同样要重载: 静默复核走的是真实 OIDC 回调,
 * 上游身份没变意味着本地会话已经被这次回调重新建立好, 重载即可让刚才 401 的请求成功;
 * 重载会重新经过后端的登录门控, 所以即使会话没恢复也只会被服务端引导到登录页, 不会在前端空转。
 */
export function identityCheckAction(
  outcome: IdentityCheckOutcome,
  trigger: IdentityCheckTrigger,
): IdentityCheckAction {
  switch (outcome) {
    case "changed":
      return "reload";
    case "logged_out":
      return "sign_in";
    case "unchanged":
      return trigger === "session_expired" ? "reload" : "none";
    case "error":
      return trigger === "session_expired" ? "session_expired_notice" : "none";
  }
}

export interface IdentityCheckMessage {
  origin: string;
  data: unknown;
}

/**
 * 从 message 事件里取结论。
 *
 * 非同源、非本协议的消息一律返回 null(页面上还有别的 postMessage 来源, 这是正常流量, 不是故障)。
 * 但同源且声明了本协议却给出未知 outcome, 说明前后端契约漂移, 必须当场抛错而不是静默忽略。
 */
export function identityCheckOutcomeFromMessage(
  message: IdentityCheckMessage,
  expectedOrigin: string,
): IdentityCheckOutcome | null {
  if (message.origin !== expectedOrigin || !isRecord(message.data)) {
    return null;
  }
  if (message.data.type !== IDENTITY_CHECK_MESSAGE_TYPE) {
    return null;
  }
  const outcome = message.data.outcome;
  if (!isIdentityCheckOutcome(outcome)) {
    throw new Error(`身份复核回调给出了未知的 outcome: ${String(outcome)}`);
  }
  return outcome;
}

function isWithinVisibleThrottle(lastCompletedAt: number | null, now: number): boolean {
  return lastCompletedAt !== null && now - lastCompletedAt < IDENTITY_CHECK_VISIBLE_THROTTLE_MS;
}

function isIdentityCheckOutcome(value: unknown): value is IdentityCheckOutcome {
  return (
    typeof value === "string" && (IDENTITY_CHECK_OUTCOMES as readonly string[]).includes(value)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
