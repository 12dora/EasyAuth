import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import type { CurrentUser } from "./App";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";
import { queryClient } from "./lib/query";
import "./styles/index.css";

const rootElement = document.getElementById("easyauth-root") ?? document.getElementById("root");

if (!rootElement) {
  throw new Error("缺少 EasyAuth React 挂载节点。");
}

const shell = readShell(rootElement);
const currentUserId = readCurrentUserId(rootElement);
const currentUser = readCurrentUser(rootElement, currentUserId);
const brandLogoUrl = readBrandLogoUrl(rootElement);

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ToastProvider>
          <BrowserRouter>
            <App brandLogoUrl={brandLogoUrl} currentUser={currentUser} currentUserId={currentUserId} shell={shell} />
          </BrowserRouter>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
);

function readShell(root: HTMLElement): "console" | "portal" {
  if (window.location.pathname.startsWith("/portal")) {
    return "portal";
  }
  const shell = root.dataset.easyauthReactShell ?? document.body.dataset.easyauthReactShell;
  if (shell === "portal") {
    return "portal";
  }
  return "console";
}

function readCurrentUserId(root: HTMLElement): string {
  return root.dataset.currentUserId ?? document.body.dataset.currentUserId ?? "";
}

function readCurrentUser(root: HTMLElement, currentUserId: string): CurrentUser | undefined {
  if (!currentUserId) {
    return undefined;
  }
  const dataset = { ...document.body.dataset, ...root.dataset };
  return {
    avatarUrl: dataset.currentUserAvatarUrl ?? "",
    displayName: dataset.currentUserDisplayName ?? "",
    id: currentUserId,
    logoutUrl: dataset.logoutUrl ?? "/auth/logout/",
    role: dataset.currentUserRole ?? "",
    isSuperuser: dataset.currentUserIsSuperuser === "true",
  };
}

function readBrandLogoUrl(root: HTMLElement): string {
  return root.dataset.brandLogoUrl ?? document.body.dataset.brandLogoUrl ?? "/assets/brand/jiefa_logo.webp";
}
