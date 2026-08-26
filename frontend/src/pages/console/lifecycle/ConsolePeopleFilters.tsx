import { TextInput } from "../../../components/Field";
import { useI18n } from "../../../i18n/I18nProvider";

/**
 * 人员列表的工具栏。
 *
 * 在职状态已经迁到表头筛选; 这里只保留 q —— 它是后端真正的姓名/邮箱/用户 ID
 * 跨列搜索, 没有任何一列能承载, 因此是唯一保留在表格外的检索框。
 */
export function ConsolePeopleFilters({
  searchInput,
  onSearchChange,
}: {
  searchInput: string;
  onSearchChange: (next: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <TextInput
        aria-label={t("people.searchPlaceholder")}
        className="w-64"
        placeholder={t("people.searchPlaceholder")}
        autoComplete="off"
        value={searchInput}
        onChange={(event) => onSearchChange(event.currentTarget.value)}
      />
    </div>
  );
}
