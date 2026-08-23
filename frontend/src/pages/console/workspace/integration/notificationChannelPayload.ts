import type { AppNotificationChannelPayload, DirectoryScopeItem } from "../../../../lib/domain";

export interface ChannelFormState {
  name: string;
  dingtalkAppKey: string;
  agentId: string;
  directorySourceSlug: string;
  corpId: string;
}

export const EMPTY_CHANNEL_FORM: ChannelFormState = {
  name: "",
  dingtalkAppKey: "",
  agentId: "",
  directorySourceSlug: "",
  corpId: "",
};

export type ChannelLoadState = "loading" | "error" | "unconfigured" | "configured";

/** 后端快照 → 表单初值; 未配置通道时回到空表单。 */
export function channelFormFromChannel(channel: NotificationChannel | null): ChannelFormState {
  if (!channel) {
    return { ...EMPTY_CHANNEL_FORM };
  }
  return {
    name: channel.name,
    dingtalkAppKey: channel.dingtalk_app_key,
    agentId: channel.agent_id,
    directorySourceSlug: channel.directory_source_slug,
    corpId: channel.corp_id,
  };
}

export function channelLoadState(isLoading: boolean, isError: boolean, channel: NotificationChannel | null): ChannelLoadState {
  if (isLoading) {
    return "loading";
  }
  if (isError) {
    return "error";
  }
  return channel ? "configured" : "unconfigured";
}

/** 当前通道绑定的目录范围是否仍在可选列表里; 未配置通道时视为有效。 */
export function currentScopeIsAvailable(scopes: DirectoryScopeItem[], channel: NotificationChannel | null): boolean {
  return channel ? scopes.some((scope) => scopeMatchesChannel(scope, channel)) : true;
}

/** 保存按钮可用条件: 三个必填项 + 已选可用目录范围 + secret 已配置或本次有输入。 */
export function channelFormComplete({
  form,
  scopes,
  channel,
  hasSecretInput,
}: {
  form: ChannelFormState;
  scopes: DirectoryScopeItem[];
  channel: NotificationChannel | null;
  hasSecretInput: boolean;
}): boolean {
  return Boolean(
    form.name.trim()
    && form.dingtalkAppKey.trim()
    && form.agentId.trim()
    && scopes.some((scope) => scopeMatchesForm(scope, form))
    && (channel?.app_secret_configured || hasSecretInput),
  );
}

type NotificationChannel = NonNullable<AppNotificationChannelPayload["notification_channel"]>;

const CHANNEL_FIELD_TYPES = {
  id: "number",
  name: "string",
  dingtalk_app_key: "string",
  app_secret_configured: "boolean",
  agent_id: "string",
  directory_source_slug: "string",
  corp_id: "string",
  version: "number",
  is_active: "boolean",
} as const;

export function parseNotificationChannelPayload(
  value: unknown,
  errorMessage: string,
  requireAvailableScopes = true,
): AppNotificationChannelPayload {
  if (!isRecord(value) || !("notification_channel" in value)) {
    throw new Error(errorMessage);
  }
  const availableDirectoryScopes = parseDirectoryScopes(value.available_directory_scopes, errorMessage, requireAvailableScopes);
  const channel = value.notification_channel;
  if (channel === null) {
    return { notification_channel: null, available_directory_scopes: availableDirectoryScopes };
  }
  if (!isRecord(channel) || !hasDeclaredChannelFieldTypes(channel)) {
    throw new Error(errorMessage);
  }
  const typedChannel = channel as unknown as NotificationChannel;
  return {
    notification_channel: {
      id: typedChannel.id,
      name: typedChannel.name,
      dingtalk_app_key: typedChannel.dingtalk_app_key,
      app_secret_configured: typedChannel.app_secret_configured,
      agent_id: typedChannel.agent_id,
      directory_source_slug: typedChannel.directory_source_slug,
      corp_id: typedChannel.corp_id,
      version: typedChannel.version,
      is_active: typedChannel.is_active,
      created_by: typeof channel.created_by === "string" ? channel.created_by : undefined,
      created_at: typeof channel.created_at === "string" ? channel.created_at : undefined,
    },
    available_directory_scopes: availableDirectoryScopes,
  };
}

/** 通道必填字段的运行时类型校验: 任一字段类型不符即视为响应非法。 */
function hasDeclaredChannelFieldTypes(channel: Record<string, unknown>): boolean {
  return Object.entries(CHANNEL_FIELD_TYPES).every(([field, expected]) => typeof channel[field] === expected);
}

function parseDirectoryScopes(value: unknown, errorMessage: string, required: boolean): DirectoryScopeItem[] {
  if (value === undefined && !required) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new Error(errorMessage);
  }
  return value.map((scope) => {
    if (!isRecord(scope) || typeof scope.directory_source_slug !== "string" || typeof scope.corp_id !== "string") {
      throw new Error(errorMessage);
    }
    return {
      directory_source_slug: scope.directory_source_slug,
      corp_id: scope.corp_id,
    };
  });
}

export function scopeKey(directorySourceSlug: string, corpId: string): string {
  return JSON.stringify([directorySourceSlug, corpId]);
}

export function scopeMatchesForm(scope: DirectoryScopeItem, form: ChannelFormState): boolean {
  return scope.directory_source_slug === form.directorySourceSlug && scope.corp_id === form.corpId;
}

export function scopeMatchesChannel(scope: DirectoryScopeItem, channel: NotificationChannel): boolean {
  return scope.directory_source_slug === channel.directory_source_slug && scope.corp_id === channel.corp_id;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
