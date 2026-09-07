/**
 * 统一登录入口: 先到 EasyAuth 自己的登录页, 由用户点「使用工作账号登录」再跳上游。
 * (旧实现指向 `/auth/local/`, 那个页面不读 next, 回跳目标会被丢掉。)
 */
export function signInUrlForCurrentPage(): string {
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return `/auth/sign-in/?next=${encodeURIComponent(next)}`;
}
