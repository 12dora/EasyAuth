/**
 * 接入应用展示名的唯一出处。
 *
 * 应用有一个技术名 `name`(由 manifest 推送覆盖, 如 "EasyCustoms"), 以及一个由管理员在控制台维护、
 * 面向员工的别名 `alias`(如 "海关数据")。任何面向用户的界面都应通过这里拼出展示名,
 * 格式固定为 `别名 (技术名)`(别名、一个半角空格、括号里的技术名); 没有别名时只显示技术名。
 */

/** 与后端 `App.alias` 的 max_length 对齐; 控制台的别名输入框据此截断。 */
export const APP_ALIAS_MAX_LENGTH = 128;

export interface AppDisplayNameSource {
  name: string;
  alias?: string | null;
}

export function formatAppDisplayName(source: AppDisplayNameSource): string {
  const alias = (source.alias ?? "").trim();
  return alias ? `${alias} (${source.name})` : source.name;
}
