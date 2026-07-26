import type { BrowserCapability } from "../lib/browserSupport";

interface UnsupportedBrowserPageProps {
  missing: BrowserCapability[];
}

const CAPABILITY_LABELS: Record<BrowserCapability, string> = {
  localStorage: "Web Storage",
  ResizeObserver: "ResizeObserver",
  "crypto.randomUUID": "crypto.randomUUID",
  secureContext: "HTTPS 安全上下文",
};

export function UnsupportedBrowserPage({ missing }: UnsupportedBrowserPageProps) {
  return (
    <main className="public-content" role="main">
      <section className="logged-out-panel" aria-labelledby="unsupported-browser-title">
        <p className="eyebrow">EasyAuth</p>
        <h1 id="unsupported-browser-title">当前浏览器或 WebView 不受支持</h1>
        <p className="page-description">
          EasyAuth 需要现代浏览器能力才能保证语言、布局测量和幂等请求安全。请使用支持矩阵中的浏览器，或联系管理员更换内置 WebView。
        </p>
        <p className="page-description">缺失能力：{missing.map((capability) => CAPABILITY_LABELS[capability]).join("、")}</p>
      </section>
    </main>
  );
}
