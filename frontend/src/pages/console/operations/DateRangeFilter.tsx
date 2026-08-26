import type { Key } from "react";

import { Button } from "../../../components/Button";
import { TextInput } from "../../../components/Field";
import type { ColumnType } from "../../../components/antd/AppTable";
import { useI18n } from "../../../i18n/I18nProvider";
import { decodeDateRange, encodeDateRange } from "./operationFilterMap";

/**
 * 时间范围筛选。antd 只内建「文本 / 枚举」两种筛选, 时间范围需要自定义下拉,
 * 这里沿用共享 textFilter 下拉的结构(输入区 + 重置/确定), 只把输入换成两个
 * datetime-local。运营页四个分区共用这一个实现。
 */

interface DateRangeFilterDropdownProps {
  selectedKeys: Key[];
  setSelectedKeys: (keys: Key[]) => void;
  confirm: (param?: { closeDropdown: boolean }) => void;
  clearFilters?: (param?: { confirm?: boolean; closeDropdown?: boolean }) => void;
}

/** 展开到列定义上: `{ ...dateTimeColumn({...}), ...dateRangeFilter<Row>() }`。 */
export function dateRangeFilter<T>(): Pick<ColumnType<T>, "filterDropdown"> {
  return {
    filterDropdown: (props) => <DateRangeFilterDropdown {...props} />,
  };
}

function DateRangeFilterDropdown({
  clearFilters,
  confirm,
  selectedKeys,
  setSelectedKeys,
}: DateRangeFilterDropdownProps) {
  const { t } = useI18n();
  const { from, to } = decodeDateRange(selectedKeys);

  return (
    // 下拉内部的键盘事件不能冒泡到表头, 否则空格/回车会触发排序。
    <div className="flex w-64 flex-col gap-2 p-2" onKeyDown={(event) => event.stopPropagation()}>
      <TextInput
        aria-label="created_from"
        type="datetime-local"
        value={from}
        onChange={(event) => setSelectedKeys(encodeDateRange({ from: event.currentTarget.value, to }))}
      />
      <TextInput
        aria-label="created_to"
        type="datetime-local"
        value={to}
        onChange={(event) => setSelectedKeys(encodeDateRange({ from, to: event.currentTarget.value }))}
      />
      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            setSelectedKeys([]);
            clearFilters?.({ confirm: true, closeDropdown: true });
          }}
        >
          {t("table.filter.reset")}
        </Button>
        <Button type="button" size="sm" variant="primary" onClick={() => confirm()}>
          {t("table.filter.confirm")}
        </Button>
      </div>
    </div>
  );
}

/**
 * 授权列表的时间范围筛选。
 *
 * 全站唯一保留在表格上方的筛选控件: 后端支持 created_from/created_to,
 * 但授权列表的载荷里没有 created_at 字段, 没有对应的列可以挂表头筛选。
 */
export function GrantCreatedRangeFilter({
  searchParams,
  onChange,
}: {
  searchParams: URLSearchParams;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <TextInput
        aria-label="created_from"
        className="w-56"
        type="datetime-local"
        value={searchParams.get("created_from") ?? ""}
        onChange={(event) => onChange("created_from", event.currentTarget.value)}
      />
      <TextInput
        aria-label="created_to"
        className="w-56"
        type="datetime-local"
        value={searchParams.get("created_to") ?? ""}
        onChange={(event) => onChange("created_to", event.currentTarget.value)}
      />
    </div>
  );
}
