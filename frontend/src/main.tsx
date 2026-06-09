import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { queryClient } from "./lib/query";
import "./styles.css";

const rootElement = document.getElementById("easyauth-root") ?? document.getElementById("root");

if (!rootElement) {
  throw new Error("缺少 EasyAuth React 挂载节点。");
}

const shell = readShell(rootElement);
const currentUserId = readCurrentUserId(rootElement);
const brandLogoUrl = readBrandLogoUrl(rootElement);

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App brandLogoUrl={brandLogoUrl} currentUserId={currentUserId} shell={shell} />
      </BrowserRouter>
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

function readBrandLogoUrl(root: HTMLElement): string {
  return root.dataset.brandLogoUrl ?? document.body.dataset.brandLogoUrl ?? "/assets/brand/jiefa_logo.webp";
}
