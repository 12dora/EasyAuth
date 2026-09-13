import { Fragment, type ReactNode } from "react";

import { Tooltip } from "antd";

import { useI18n } from "../../../i18n/I18nProvider";
import type { AccountKind, PersonRef } from "../../../lib/domain/person";
import { joinLabels } from "../../../lib/joinLabels";
import type { Translator } from "../../../lib/status";
import { TruncatedText } from "../../TruncatedText";
import { personNameWithDepartment, userOptionName, userSecondaryLabel } from "../../UserCombobox";
import { textFilter, type ColumnType } from "../AppTable";
import { MONO_TEXT_CLASS } from "./text";

/** 人员列客户端排序的 locale: 姓名与次行都按中文排序。 */
export const PERSON_SORT_LOCALE = "zh-Hans-CN";

/**
 * 人员 / 用户列客户端比较: 先姓名(主行)后次行, 都走 `zh-Hans-CN`。
 */
export function comparePersonLines(
  left: { name: string; secondary: string },
  right: { name: string; secondary: string },
): number {
  const nameCmp = left.name.localeCompare(right.name, PERSON_SORT_LOCALE);
  if (nameCmp !== 0) {
    return nameCmp;
  }
  return left.secondary.localeCompare(right.secondary, PERSON_SORT_LOCALE);
}

export interface UserColumnConfig<T> {
  key?: string;
  title?: ReactNode;
  /** 主行: 显示名。 */
  getName: (record: T) => string | null | undefined;
  /**
   * 姓名缺失时的主行回退, 以及未传 `getSecondary` 时的次行(应用 key / 邮箱等标识符)。
   *
   * 人员列必须走 `personColumn` / `peopleColumn`: 不要把 Authentik UUID 或 user_id
   * 传到这里当次行, 也不要用 `textColumn` + `safeJoin` 拼接 owners / user_ids。
   */
  getUserId?: (record: T) => string | null | undefined;
  /** 次行文案; 传入后覆盖 `getUserId` 作为次行(主行回退仍用 `getUserId`)。 */
  getSecondary?: (record: T) => string | null | undefined;
  /**
   * 次行是否等宽。默认: 走 `getSecondary` 时 false(部门路径), 只走 `getUserId` 时 true(标识符)。
   */
  mono?: boolean;
  /** 开启文本筛选(同时匹配显示名与次行)。 */
  filter?: boolean;
  /**
   * 开启客户端排序: 先主行姓名, 再次行, 都走 `zh-Hans-CN`。
   * 服务端分页表不要开, 改过 `serverSortColumn`。
   */
  sorter?: boolean;
  width?: number;
}

export interface PersonColumnConfig<T> {
  key?: string;
  title?: ReactNode;
  getName: (record: T) => string | null | undefined;
  getUserId: (record: T) => string | null | undefined;
  /** 部门路径; 缺省或空串时次行留空(本地账号除外, 见 `userSecondaryLabel`)。 */
  getDepartment?: (record: T) => string | null | undefined;
  /** 账号类型; `local` 时次行固定为「本地用户」, 即使 user_id 是 UUID。 */
  getAccountKind?: (record: T) => AccountKind | undefined;
  /** 本地账号次行文案需要 t("user.localAccount")。 */
  t: Translator;
  filter?: boolean;
  /** 开启客户端排序(姓名然后次行); 服务端表改过 `serverSortColumn`。 */
  sorter?: boolean;
  width?: number;
}

export interface PeopleColumnConfig<T> {
  key?: string;
  title?: ReactNode;
  getPeople: (record: T) => readonly PersonRef[] | null | undefined;
  t: Translator;
  filter?: boolean;
  /** 开启客户端排序: 按第一负责人姓名然后次行, 同位再比后续人员。服务端表改过 `serverSortColumn`。 */
  sorter?: boolean;
  width?: number;
}

/**
 * 用户列: 显示名 + 次行两行。
 * 沿用 ConsoleTeamMemberTable / MembershipsPanel 既有的成员单元格排版。
 * 表格内不渲染头像; 头像只出现在顶栏用户摘要。
 *
 * 次行默认等宽, 给应用 key / 邮箱这类标识符用; 人员部门请走 `personColumn`。
 */
export function userColumn<T>({
  filter = false,
  getName,
  getUserId,
  getSecondary,
  mono,
  key = "user",
  sorter = false,
  title,
  width,
}: UserColumnConfig<T>): ColumnType<T> {
  const secondaryIsMono = mono ?? getSecondary === undefined;
  const read = (record: T) => {
    const name = getName(record);
    const userId = getUserId?.(record);
    const secondary = getSecondary
      ? getSecondary(record)
      : userId;
    return {
      name: name === null || name === undefined ? "" : String(name),
      userId: userId === null || userId === undefined ? "" : String(userId),
      secondary: secondary === null || secondary === undefined ? "" : String(secondary),
    };
  };

  return {
    key,
    title: title ?? <UserColumnTitle />,
    width,
    render: (_value: unknown, record: T) => {
      const { name, userId, secondary } = read(record);
      const displayName = name || userId;
      if (displayName === "" && secondary === "") {
        return "-";
      }
      // 未传 getSecondary 时保持旧语义: 次行是标识符, 只有主行已有姓名才展示, 避免 UUID 自己复制成两行。
      const showSecondary = getSecondary ? secondary !== "" : Boolean(userId && name);
      return (
        <div className="flex min-w-0 flex-col gap-1">
          <strong className="truncate">{displayName || secondary}</strong>
          {showSecondary ? (
            <TruncatedText
              as={secondaryIsMono ? "code" : "span"}
              className={secondaryIsMono ? MONO_TEXT_CLASS : "text-body leading-5 text-ink-soft"}
              text={secondary}
            />
          ) : null}
        </div>
      );
    },
    ...(filter
      ? textFilter<T>(key, {
          getValue: (record) => {
            const { name, userId, secondary } = read(record);
            return `${name || userId} ${secondary}`;
          },
        })
      : {}),
    ...(sorter
      ? {
          sorter: (a: T, b: T) => {
            const left = read(a);
            const right = read(b);
            return comparePersonLines(
              { name: left.name || left.userId, secondary: left.secondary },
              { name: right.name || right.userId, secondary: right.secondary },
            );
          },
        }
      : {}),
  };
}

/**
 * 人员列: 姓名 + 部门路径(或「本地用户」)两行, 次行绝不出 UUID。
 * 姓名缺失时主行仍回退到 user_id, 与 `userOptionName` 同一条规则。
 */
export function personColumn<T>({
  filter = false,
  getAccountKind,
  getDepartment,
  getName,
  getUserId,
  key = "user",
  sorter = false,
  t,
  title,
  width,
}: PersonColumnConfig<T>): ColumnType<T> {
  return userColumn<T>({
    filter,
    getName,
    getUserId,
    getSecondary: (record) =>
      userSecondaryLabel(
        {
          user_id: String(getUserId(record) ?? ""),
          department: getDepartment?.(record) ?? "",
          account_kind: getAccountKind?.(record),
        },
        t,
      ),
    key,
    mono: false,
    sorter,
    title,
    width,
  });
}

/**
 * 多人列: 姓名以 `, ` 写在同一行, 超长由 TruncatedText 截断;
 * 悬停单个姓名才出部门(或「本地用户」)。溢出 Tooltip 只在指针落在姓名 span 以外时打开,
 * 内容是每人一行「姓名 · 部门」, 避免与单人部门 Tooltip 叠开。次行绝不出 UUID。
 */
export function peopleColumn<T>({
  filter = false,
  getPeople,
  key = "people",
  sorter = false,
  t,
  title,
  width,
}: PeopleColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => getPeople(record) ?? [];
  const line = (person: PersonRef) => ({
    name: userOptionName(person),
    secondary: userSecondaryLabel(person, t),
  });

  return {
    key,
    title,
    width,
    render: (_value: unknown, record: T) => {
      const people = read(record);
      if (people.length === 0) {
        return "-";
      }
      return <PeopleLine people={people} t={t} />;
    },
    ...(filter
      ? textFilter<T>(key, {
          getValue: (record) =>
            read(record)
              .map((person) => `${userOptionName(person)} ${userSecondaryLabel(person, t)}`)
              .join(" "),
        })
      : {}),
    ...(sorter
      ? {
          sorter: (a: T, b: T) => {
            const left = read(a);
            const right = read(b);
            const n = Math.max(left.length, right.length);
            for (let index = 0; index < n; index += 1) {
              const leftPerson = left[index];
              const rightPerson = right[index];
              const cmp = comparePersonLines(
                leftPerson ? line(leftPerson) : { name: "", secondary: "" },
                rightPerson ? line(rightPerson) : { name: "", secondary: "" },
              );
              if (cmp !== 0) {
                return cmp;
              }
            }
            return 0;
          },
        }
      : {}),
  };
}

const PEOPLE_NAME_SEPARATOR = ", ";

function PeopleLine({ people, t }: { people: readonly PersonRef[]; t: Translator }) {
  const joined = joinLabels(
    people.map((person) => userOptionName(person)),
    { separator: PEOPLE_NAME_SEPARATOR },
  );
  return (
    <TruncatedText className="block w-full min-w-0" text={joined} title={<PeopleOverflowTitle people={people} t={t} />}>
      {people.map((person, index) => (
        <Fragment key={person.user_id}>
          {index > 0 ? PEOPLE_NAME_SEPARATOR : null}
          <PersonName person={person} t={t} />
        </Fragment>
      ))}
    </TruncatedText>
  );
}

function PeopleOverflowTitle({ people, t }: { people: readonly PersonRef[]; t: Translator }) {
  return people.map((person) => <div key={person.user_id}>{personNameWithDepartment(person, t)}</div>);
}

function PersonName({ person, t }: { person: PersonRef; t: Translator }) {
  const name = userOptionName(person);
  const secondary = userSecondaryLabel(person, t);
  const body = <span data-tooltip-child="">{name}</span>;
  if (!secondary) {
    return body;
  }
  return <Tooltip title={secondary}>{body}</Tooltip>;
}

function UserColumnTitle() {
  const { t } = useI18n();
  return <>{t("table.column.user")}</>;
}
