export type BrowserCapability =
  | "localStorage"
  | "ResizeObserver"
  | "crypto.randomUUID"
  | "secureContext";

export interface BrowserSupportResult {
  supported: boolean;
  missing: BrowserCapability[];
}

export function checkBrowserSupport(): BrowserSupportResult {
  const missing: BrowserCapability[] = [];

  if (!hasLocalStorage()) {
    missing.push("localStorage");
  }
  if (typeof ResizeObserver === "undefined") {
    missing.push("ResizeObserver");
  }
  if (!globalThis.crypto?.randomUUID) {
    missing.push("crypto.randomUUID");
  }
  if (!isSecureAppContext()) {
    missing.push("secureContext");
  }

  return { supported: missing.length === 0, missing };
}

function hasLocalStorage(): boolean {
  try {
    const key = "__easyauth_support_probe__";
    window.localStorage.setItem(key, "1");
    window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

function isSecureAppContext(): boolean {
  return window.isSecureContext || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
}
