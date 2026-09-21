/**
 * 用量监控的配色与记号规格 —— 全页(计量条 + 图表 + 图例 + 表格占比条)唯一来源。
 *
 * 取值不是手挑的: 候选色来自控制台既有令牌所属的色阶(accent = blue-600,
 * signal = red-700, evergreen = emerald-700), 再用配色校验器在白底、
 * Machado 2009 色觉模拟下跑过六项检查:
 *
 *   堆叠三序列 #2563EB / #D97706 / #047857 + 被拒绝 #B91C1C
 *     → 全对比(--pairs all)最差 ΔE 8.4(deutan)、常视觉 18.8, 六项全 PASS。
 *   严重度三档 #2563EB / #D97706 / #B91C1C
 *     → 全对比最差 ΔE 16.2(deutan)、常视觉 18.8, 六项全 PASS。
 *
 * 两处有意的偏离, 都有校验结论支撑:
 * 1. 填充用的琥珀是 amber-600 `#D97706`, 不是文字令牌 `--amber`(amber-800 `#92400E`)。
 *    `#92400E` 与 `#B91C1C` 的常视觉 ΔE 只有 8.9(< 15 硬门槛), 两档会糊在一起;
 *    amber-800 仍然是**文字**色(白底 7.09:1), 见 SEVERITY_TEXT_CLASS。
 * 2. 严重度只有三种色相: 「告警」与「超限」同为 signal 红, 超限额外用
 *    斜纹溢出段 + 脉冲状态药丸区分 —— 红色阶内再劈一档无法通过常视觉 ΔE >= 15。
 */

export type UsageSeverity = "normal" | "attention" | "warning" | "critical";

/** 堆叠序列(标识色, 固定顺序, 不循环)。 */
export const USAGE_SERIES_COLOR = {
  api_billed: "#2563EB",
  api_unbilled: "#D97706",
  internal: "#047857",
  /** 被拒绝是状态色, 不参与标识色位次。 */
  blocked: "#B91C1C",
} as const;

/** 单序列小图(Webhook / Stream)用第 1 位标识色; 标题已经点明画的是什么, 不需要图例。 */
export const USAGE_SINGLE_SERIES_COLOR = USAGE_SERIES_COLOR.api_billed;

export const USAGE_SEVERITY_FILL: Record<UsageSeverity, string> = {
  normal: "#2563EB",
  attention: "#D97706",
  warning: "#B91C1C",
  critical: "#B91C1C",
};

/** 填充用同色阶的浅 → 深渐变, 数据端落在满饱和的那一头。 */
const SEVERITY_GRADIENT_START: Record<UsageSeverity, string> = {
  normal: "#60A5FA",
  attention: "#FBBF24",
  warning: "#EF4444",
  critical: "#EF4444",
};

/** 文字永远穿文字令牌, 不穿数据色。 */
export const SEVERITY_TEXT_CLASS: Record<UsageSeverity, string> = {
  normal: "text-ink",
  attention: "text-amber",
  warning: "text-signal",
  critical: "text-signal",
};

export function usageMeterGradient(severity: UsageSeverity): string {
  return `linear-gradient(90deg, ${SEVERITY_GRADIENT_START[severity]} 0%, ${USAGE_SEVERITY_FILL[severity]} 100%)`;
}

/** 未填充轨道 = 同一严重度色的极浅一档, 状态因此读得穿整条。 */
export function usageMeterTrack(severity: UsageSeverity): string {
  return withAlpha(USAGE_SEVERITY_FILL[severity], 0.12);
}

/** 超过 100% 的溢出段: 45° 斜纹, 色相之外再给一层非颜色的区分。 */
export function usageOverflowFill(): string {
  const base = USAGE_SEVERITY_FILL.critical;
  return `repeating-linear-gradient(45deg, ${base} 0 4px, ${withAlpha(base, 0.45)} 4px 8px)`;
}

export function withAlpha(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const red = Number.parseInt(value.slice(0, 2), 16);
  const green = Number.parseInt(value.slice(2, 4), 16);
  const blue = Number.parseInt(value.slice(4, 6), 16);
  return `rgb(${red} ${green} ${blue} / ${alpha})`;
}

/** 记号规格(见 dataviz 的 marks-and-anatomy): 柱 <= 24px、线 2px、栅格发丝线。 */
export const USAGE_CHART_MARKS = {
  barMaxWidth: 18,
  lineWidth: 2,
  dotRadius: 4,
  /**
   * 相邻填充之间留 2px 背景色缝。recharts 没有「堆叠间距」, 实现方式是给每段
   * 描一圈 2px 的**背景色**边 —— 画出来就是缝, 卡片本身也是白底, 外缘那一圈看不见。
   */
  stackGap: 2,
  surface: "#FFFFFF",
  gridColor: "rgb(226 232 240)",
  axisTextColor: "rgb(100 116 139)",
  tickFontSize: 11,
} as const;
