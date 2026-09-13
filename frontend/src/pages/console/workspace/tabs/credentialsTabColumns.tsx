import { Pencil } from "lucide-react";

import { enumFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import { RowActionButton, actionsColumn, activeStatusColumn, textColumn } from "../../../../components/antd/columns";
import { Badge } from "../../../../components/Badge";
import type { AppCapabilityKey, CredentialItem } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { credentialKindLabel } from "../utils";

export function buildCredentialColumns({
  canManage,
  t,
  isCredentialPending,
  onEditCapabilities,
  onRotate,
  onDisable,
}: {
  canManage: boolean;
  t: Translator;
  isCredentialPending: (credential: CredentialItem) => boolean;
  onEditCapabilities: (credential: CredentialItem) => void;
  onRotate: (credential: CredentialItem) => void;
  onDisable: (credential: CredentialItem) => void;
}): ColumnsType<CredentialItem> {
  return [
    textColumn<CredentialItem>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    {
      key: "kind",
      dataIndex: "kind",
      title: t("common.type"),
      width: 140,
      sorter: (a: CredentialItem, b: CredentialItem) =>
        credentialKindLabel(a.kind).localeCompare(credentialKindLabel(b.kind)),
      render: (_value: unknown, credential: CredentialItem) => credentialKindLabel(credential.kind),
      ...enumFilter<CredentialItem>("kind", [
        { label: credentialKindLabel("static_token"), value: "static_token" },
        { label: credentialKindLabel("oauth_client"), value: "oauth_client" },
      ]),
    },
    textColumn<CredentialItem>({
      key: "client_id",
      title: "client_id",
      mono: true,
      filter: true,
      sorter: true,
      width: 220,
    }),
    {
      key: "capabilities",
      title: t("console.credentials.capabilities"),
      width: 200,
      sorter: (a: CredentialItem, b: CredentialItem) =>
        (a.capabilities ?? []).join(",").localeCompare((b.capabilities ?? []).join(",")),
      render: (_value: unknown, credential: CredentialItem) => (
        <div className="flex min-w-36 flex-wrap gap-1">
          {(credential.capabilities ?? []).length > 0 ? (
            credential.capabilities?.map((capability) => <Badge key={capability} tone="bond">{capability}</Badge>)
          ) : (
            <Badge tone="faint">{t("console.credentials.permissionOnly")}</Badge>
          )}
        </div>
      ),
      // 能力是多值, 未授予任何能力的凭据归到「仅权限查询」这一档。
      ...enumFilter<CredentialItem>(
        "capabilities",
        [
          { label: "directory", value: "directory" },
          { label: "notify", value: "notify" },
          { label: t("console.credentials.permissionOnly"), value: "none" },
        ],
        {
          getValue: (credential) => ((credential.capabilities ?? []).length > 0 ? (credential.capabilities ?? []) : ["none"]),
        },
      ),
    },
    activeStatusColumn<CredentialItem>({ t, getActive: (credential) => credential.is_active }),
    actionsColumn<CredentialItem>({
      title: t("common.actions"),
      render: (credential) => (
        <CredentialRowActions
          canManage={canManage}
          credential={credential}
          t={t}
          isPending={isCredentialPending(credential)}
          onEditCapabilities={onEditCapabilities}
          onRotate={onRotate}
          onDisable={onDisable}
        />
      ),
    }),
  ];
}

function CredentialRowActions({
  canManage,
  credential,
  t,
  isPending,
  onEditCapabilities,
  onRotate,
  onDisable,
}: {
  canManage: boolean;
  credential: CredentialItem;
  t: Translator;
  isPending: boolean;
  onEditCapabilities: (credential: CredentialItem) => void;
  onRotate: (credential: CredentialItem) => void;
  onDisable: (credential: CredentialItem) => void;
}) {
  return (
    <>
      {canManage ? (
        <RowActionButton type="button" disabled={isPending} onClick={() => onEditCapabilities(credential)}>
          <Pencil size={13} aria-hidden="true" />
          {t("console.credentials.editCapabilities")}
        </RowActionButton>
      ) : null}
      {canManage && credential.kind === "static_token" ? (
        <RowActionButton type="button" disabled={isPending} onClick={() => onRotate(credential)}>
          {t("console.credentials.rotate")}
        </RowActionButton>
      ) : null}
      {canManage ? (
        <RowActionButton type="button" variant="ghost-danger" disabled={isPending} onClick={() => onDisable(credential)}>
          {t("console.credentials.disable")}
        </RowActionButton>
      ) : (
        <span className="text-xs text-ink-faint">{t("console.integration.readOnlyMode")}</span>
      )}
    </>
  );
}

export type { AppCapabilityKey };
