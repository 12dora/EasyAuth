import type { ThemeConfig } from "antd";

/**
 * antd 主题令牌的唯一映射出处。
 *
 * 这里的字面量值必须与 src/styles/index.css `:root` 里的设计令牌逐一对应:
 * antd 需要能被 @ant-design/colors 解析的具体色值来派生 hover/active 色阶,
 * 直接写 `rgb(var(--accent))` 会让派生失败, 所以只能复制成十六进制值。
 * 改动 index.css 的令牌时必须同步改这里, 否则 antd 控件会与自研控件漂移。
 */
export const DESIGN_TOKENS = {
  /** --paper 255 255 255 */
  paper: "#ffffff",
  /** --paper-deep 248 250 252 */
  paperDeep: "#f8fafc",
  /** --ink 15 23 42 */
  ink: "#0f172a",
  /** --ink-soft 71 85 105 */
  inkSoft: "#475569",
  /** --ink-faint 100 116 139 */
  inkFaint: "#64748b",
  /** --hairline 226 232 240 */
  hairline: "#e2e8f0",
  /** --hairline-strong 203 213 225 */
  hairlineStrong: "#cbd5e1",
  /** --hairline-soft 241 245 249 */
  hairlineSoft: "#f1f5f9",
  /** --accent 37 99 235 */
  accent: "#2563eb",
  /** --amber 146 64 14 */
  amber: "#92400e",
  /** --signal 185 28 28 */
  signal: "#b91c1c",
  /** --bond 67 56 202 */
  bond: "#4338ca",
  /** --evergreen 4 120 87 */
  evergreen: "#047857",
  /** --font-sans */
  fontSans:
    '"Geist Variable", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif',
  /** --font-mono */
  fontMono: '"Geist Mono Variable", "SFMono-Regular", Consolas, "Liberation Mono", ui-monospace, monospace',
} as const;

/**
 * 控件高度必须与 src/components/Button.tsx 的 BUTTON_SIZE_CLASSES 完全一致,
 * antd 控件与自研 Button 并排时不能差一个像素:
 * sm h-7 = 28px / md h-9 = 36px / lg h-11 = 44px。
 */
export const CONTROL_HEIGHT_SM = 28;
export const CONTROL_HEIGHT = 36;
export const CONTROL_HEIGHT_LG = 44;

/**
 * 行悬停底色 = Tailwind 的 `hover:bg-accent/5`(TABLE_ROW_CLASS)。
 *
 * 半透明色对固定列(`fixed: "left"/"right"`)是不成立的: 横向滚动的单元格会从底下透上来。
 * src/styles/features/app-table.css 把这个值合成到 colorBgContainer 之上、写成不透明的
 * `#f4f7fe` 再钉给固定单元格; 改这里必须同改那边, AppTable.test.tsx 会断言两边一致。
 */
export const ROW_HOVER_BG = "rgba(37, 99, 235, 0.05)";

/**
 * 应用尚无深色主题(index.css 固定 `color-scheme: light`, 全仓无 `dark:` 变体、
 * 无 prefers-color-scheme 查询), 因此不配置 theme.algorithm;
 * 将来接入深色时在这里追加 `algorithm: theme.darkAlgorithm` 即可。
 */
export const APP_ANTD_THEME: ThemeConfig = {
  token: {
    colorPrimary: DESIGN_TOKENS.accent,
    colorInfo: DESIGN_TOKENS.accent,
    colorLink: DESIGN_TOKENS.accent,
    colorSuccess: DESIGN_TOKENS.evergreen,
    colorWarning: DESIGN_TOKENS.amber,
    colorError: DESIGN_TOKENS.signal,

    colorText: DESIGN_TOKENS.ink,
    colorTextSecondary: DESIGN_TOKENS.inkSoft,
    colorTextTertiary: DESIGN_TOKENS.inkFaint,
    colorTextQuaternary: DESIGN_TOKENS.inkFaint,

    colorBgContainer: DESIGN_TOKENS.paper,
    colorBgElevated: DESIGN_TOKENS.paper,
    colorBgLayout: DESIGN_TOKENS.paperDeep,
    colorFillAlter: DESIGN_TOKENS.paperDeep,

    colorBorder: DESIGN_TOKENS.hairlineStrong,
    colorBorderSecondary: DESIGN_TOKENS.hairline,

    fontFamily: DESIGN_TOKENS.fontSans,
    fontFamilyCode: DESIGN_TOKENS.fontMono,
    // --text-body 13px / --text-caption 12px
    fontSize: 13,
    fontSizeSM: 12,
    fontSizeLG: 14,

    // paper-card 圆角 3px, Button 圆角 2px; antd 的常规控件对齐 Button。
    borderRadius: 2,
    borderRadiusXS: 2,
    borderRadiusSM: 2,
    borderRadiusLG: 3,

    controlHeightSM: CONTROL_HEIGHT_SM,
    controlHeight: CONTROL_HEIGHT,
    controlHeightLG: CONTROL_HEIGHT_LG,

    lineWidth: 1,
    wireframe: false,
    motionEaseOut: "cubic-bezier(0.16, 1, 0.3, 1)",
  },
  components: {
    Table: {
      headerBg: DESIGN_TOKENS.paperDeep,
      headerColor: DESIGN_TOKENS.inkSoft,
      headerSplitColor: "transparent",
      headerBorderRadius: 2,
      borderColor: DESIGN_TOKENS.hairline,
      rowHoverBg: ROW_HOVER_BG,
      footerBg: DESIGN_TOKENS.paperDeep,
      // TABLE_CELL_CLASS 的 px-3 py-2.5 = 12px / 10px。
      cellPaddingBlockMD: 10,
      cellPaddingInlineMD: 12,
      cellPaddingBlockSM: 8,
      cellPaddingInlineSM: 10,
    },
  },
};
