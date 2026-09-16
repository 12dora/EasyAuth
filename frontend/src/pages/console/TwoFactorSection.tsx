import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { Button } from "../../components/Button";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { SettingsCard } from "./SettingsCard";
import { PasskeyRow } from "./TwoFactorPasskeyRow";
import { TotpRow } from "./TwoFactorTotpRow";
import { BASE_URL, TWO_FACTOR_KEY, type Translate, type TwoFactorStatus } from "./twoFactorModel";

export function TwoFactorSection() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const statusQuery = useQuery({
    queryKey: TWO_FACTOR_KEY,
    queryFn: () => apiRequest<TwoFactorStatus>(BASE_URL),
  });
  const status = statusQuery.data;

  if (statusQuery.isLoading) {
    return (
      <TwoFactorCard t={t}>
        <p className="text-body text-ink-faint">{t("common.loading")}</p>
      </TwoFactorCard>
    );
  }

  if (statusQuery.error) {
    return (
      <TwoFactorCard t={t}>
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("settings.twoFactor.loadFailed")}
          message={(statusQuery.error as Error).message}
        />
        <Button type="button" onClick={() => void statusQuery.refetch()}>
          {t("common.retry")}
        </Button>
      </TwoFactorCard>
    );
  }

  // 非本地管理员(OIDC 管理员的两步验证由上游 Authentik 管理)由后端显式 supported=false 表达。
  if (!status?.supported) {
    return null;
  }

  const applyStatus = (next: TwoFactorStatus) => {
    queryClient.setQueryData(TWO_FACTOR_KEY, next);
  };

  return (
    <TwoFactorCard t={t}>
      <div className="divide-y divide-ink/10 border-t border-ink/10">
        <TotpRow t={t} enabled={status.totp.enabled} onStatus={applyStatus} />
        <PasskeyRow t={t} passkeys={status.passkeys} onStatus={applyStatus} />
      </div>
    </TwoFactorCard>
  );
}

/** 正常态与加载中/加载失败共用同一张卡片外框, 标题始终可见, 主体让位给状态。 */
function TwoFactorCard({ t, children }: { t: Translate; children: ReactNode }) {
  return (
    <SettingsCard
      eyebrow={t("settings.eyebrow.security")}
      title={t("settings.twoFactor.title")}
      description={t("settings.twoFactor.description")}
      titleTestId="two-factor-title"
      data-test-id="two-factor-card"
    >
      {children}
    </SettingsCard>
  );
}
