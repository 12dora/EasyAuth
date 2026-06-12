import { useLocation } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { AccessRequestForm } from "./components/AccessRequestForm";
import { GrantTable } from "./components/GrantTable";
import { RequestTable } from "./components/RequestTable";

type PortalView = "grants" | "request" | "requests" | "expiring";

export function PortalPage() {
  const location = useLocation();
  const view = portalViewFromPath(location.pathname);

  return (
    <>
      <PageHeader
        eyebrow="Portal"
        title={viewTitle(view)}
        description="按当前员工 session 查看授权、申请记录和到期提醒。"
      />
      {view === "grants" ? <GrantTable endpoint="/portal/api/v1/me/grants" emptyText="暂无当前授权" /> : null}
      {view === "expiring" ? <GrantTable endpoint="/portal/api/v1/me/grants/expiring" emptyText="暂无即将过期授权" /> : null}
      {view === "requests" ? <RequestTable /> : null}
      {view === "request" ? <AccessRequestForm /> : null}
    </>
  );
}

function portalViewFromPath(pathname: string): PortalView {
  if (pathname.endsWith("/request")) {
    return "request";
  }
  if (pathname.endsWith("/requests")) {
    return "requests";
  }
  if (pathname.endsWith("/expiring")) {
    return "expiring";
  }
  return "grants";
}

function viewTitle(view: PortalView): string {
  switch (view) {
    case "request":
      return "申请权限";
    case "requests":
      return "我的申请";
    case "expiring":
      return "即将过期";
    default:
      return "我的权限";
  }
}
