interface UserSummaryProps {
  currentUserId?: string;
  mode: "console" | "portal";
}

export function UserSummary({ currentUserId = "", mode }: UserSummaryProps) {
  const normalizedUserId = currentUserId.trim();
  const userName = normalizedUserId || (mode === "console" ? "系统管理员" : "当前用户");
  const userRole = mode === "console" ? "平台运营" : "员工门户";
  const avatarLabel = normalizedUserId ? normalizedUserId.slice(0, 1).toUpperCase() : mode === "console" ? "管" : "员";

  return (
    <>
      <div className="user-summary">
        <strong>{userName}</strong>
        <span>{userRole}</span>
      </div>
      <span className="avatar" aria-label="当前用户头像" role="img">
        {avatarLabel}
      </span>
    </>
  );
}
