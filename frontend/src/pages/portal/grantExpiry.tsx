import { useI18n } from "../../i18n/I18nProvider";
import { grantTypeLabel } from "../../lib/status";

/**
 * 「期限 + 过期时间」合并成的一格, 门户两张表和申请详情弹窗共用。
 *
 * 期限只有三种取值, 单独占一列却又和过期时间必然一起读(长期授权的过期时间恒为空、
 * 限时授权的期限恒为「限时」), 因此并到一格里: 长期给期限标签, 限时给到期时刻,
 * 混合期限在时刻后补上标签。
 */
export function GrantExpiryCell({
  grantType,
  expiresAt,
}: {
  grantType: string | undefined;
  expiresAt: string | null | undefined;
}) {
  const { formatDateTime, t } = useI18n();
  if (grantType === "permanent") {
    return <span className="whitespace-nowrap">{grantTypeLabel(t, grantType)}</span>;
  }
  const formatted = formatDateTime(expiresAt);
  if (grantType === "mixed") {
    return <span className="tabular">{t("portal.grants.expiresAtMixed", { expiresAt: formatted, term: grantTypeLabel(t, grantType) })}</span>;
  }
  return <span className="whitespace-nowrap tabular">{formatted}</span>;
}
