/** 本模块定义 Connector 与 Webhook 领域契约。 */

import type { JsonObject } from "./common";

/** 应用 Webhook 配置: secret 明文只在轮换/首次保存的 PUT 响应中出现一次。 */
export interface WebhookConfigItem {
  enabled: boolean;
  secret_configured: boolean;
  approval_callback_url: string;
  handover_url: string;
  onboard_url: string;
  updated_by?: string;
  updated_at?: string | null;
  secret?: string;
}

export interface WebhookConfigPayload {
  webhook_config: WebhookConfigItem | null;
}

/** 出站供给连接器 config_schema 的字段描述(JSON Schema 子集, x-secret 标记加密字段)。 */
export interface ConnectorSchemaProperty {
  type?: "string" | "boolean" | "number" | string;
  title?: string;
  description?: string;
  default?: string | number | boolean;
  enum?: Array<string | number>;
  "x-secret"?: boolean;
}

export interface ConnectorConfigSchema {
  type?: string;
  properties?: Record<string, ConnectorSchemaProperty>;
  required?: string[];
}

export interface ConnectorTypeItem {
  key: string;
  display_name: string;
  config_schema: ConnectorConfigSchema;
}

export interface ConnectorReconcileState {
  status: "idle" | "queued" | "running" | "dirty" | string;
  generation: number;
  reconciled_generation: number;
  dirty: boolean;
  pending_trigger: "periodic" | "event" | "manual" | "offboard" | string;
  worker_queued: boolean;
  worker_queued_at: string | null;
  lease_active: boolean;
  lease_expires_at: string | null;
}

export interface ConnectorExternalGroupsRefreshState {
  status: "" | "running" | "success" | "failed" | string;
  cursor: string;
  refreshed_at: string | null;
}

/** 连接器实例: config 中 x-secret 字段读接口恒为空串, configured_secrets 标记已配置。 */
export interface ConnectorInstanceItem {
  id: number;
  connector_key: string;
  display_name: string;
  enabled: boolean;
  config: JsonObject;
  configured_secrets: string[];
  reconcile_interval_seconds: number;
  last_reconcile_at: string | null;
  last_status: "" | "success" | "partial" | "failed" | string;
  last_error: string;
  consecutive_failures: number;
  external_groups_refresh?: ConnectorExternalGroupsRefreshState;
  updated_by: string;
  reconcile_state: ConnectorReconcileState;
  updated_at: string;
}

export interface ConnectorsPayload {
  connector_types: ConnectorTypeItem[];
  data: ConnectorInstanceItem[];
}

export interface ConnectorInstancePayload {
  connector: ConnectorInstanceItem;
}

export interface ConnectorTestResult {
  ok: boolean;
  message: string;
}

export interface ConnectorMappingItem {
  authorization_group_key: string;
  authorization_group_name: string;
  external_ref: string;
  auto_create: boolean;
}

export interface ConnectorExternalGroupItem {
  ref: string;
  name: string;
}

export interface ConnectorSyncRunItem {
  id: number;
  trigger: "periodic" | "event" | "manual" | "offboard" | string;
  status: "success" | "partial" | "failed" | string;
  started_at: string;
  finished_at: string;
  stats: Record<string, number>;
  error: string;
}

