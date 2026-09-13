import { useI18n } from "../../i18n/I18nProvider";
import { OrgTreeItem, OrgTreeRuntimeContext } from "./OrgTreeItem";
import { nodeName, type OrgTreeNode, type OrgTreeProps } from "./orgTreeModel";
import { useOrgTree } from "./useOrgTree";

export type { OrgTreeNode, OrgTreeProps };

/**
 * 受控的部门树。
 *
 * 点整行即"选中 + 展开/收起"(叶子只选中), 三角是同一动作的次级把手。
 * 键盘按 WAI-ARIA tree 约定: 上下移动、右展开(已展开则进入首个子节点)、
 * 左收起(已收起则回到父节点)、Enter 选中; 焦点用 roving tabindex, 整棵树只有一个
 * tab 停靠点。展开/收起动画见 `styles/features/org-tree.css`, 动画只作用在子层容器上,
 * 因此不会挡住选中的即时反馈。
 */
export function OrgTree({
  root,
  selectedDeptId,
  expandedDeptIds,
  onSelect,
  onExpandedChange,
  filter = "",
  labelFor = nodeName,
}: OrgTreeProps) {
  const { t } = useI18n();
  const { runtime, handleKeyDown, rootVisible } = useOrgTree({
    root,
    selectedDeptId,
    expandedDeptIds,
    onSelect,
    onExpandedChange,
    filter,
    labelFor,
  });

  if (!rootVisible) {
    return <p className="org-tree__empty">{t("departmentGrants.tree.noMatch")}</p>;
  }

  return (
    <OrgTreeRuntimeContext.Provider value={runtime}>
      <div className="org-tree" role="tree" aria-label={t("departmentGrants.tree.ariaLabel")} onKeyDown={handleKeyDown}>
        <OrgTreeItem node={root} depth={0} />
      </div>
    </OrgTreeRuntimeContext.Provider>
  );
}
