import { ChevronRight } from "lucide-react";
import { createContext, memo, useContext, useSyncExternalStore } from "react";
import type { CSSProperties } from "react";

import { TruncatedText } from "../../components/TruncatedText";
import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import type { OrgTreeNode, OrgTreeRowStateStore } from "./orgTreeModel";

/** 行组件要用到的、整棵树共享且引用稳定的东西; 变了才值得让所有行重渲染(换过滤、换根)。 */
export interface OrgTreeRuntime {
  labelFor: (node: OrgTreeNode) => string;
  visibleDeptIds: Set<string>;
  rowStates: OrgTreeRowStateStore;
  /** 点整行: 选中并就地展开/收起。第二个参数是该行当前的展开态。 */
  selectRow: (node: OrgTreeNode, expanded: boolean) => void;
  /** 点三角: 只展开/收起。 */
  toggleRow: (node: OrgTreeNode, expanded: boolean) => void;
  focusRow: (deptId: string) => void;
  registerItem: (deptId: string, element: HTMLDivElement | null) => void;
}

export const OrgTreeRuntimeContext = createContext<OrgTreeRuntime | null>(null);

export function useOrgTreeRuntime(): OrgTreeRuntime {
  const runtime = useContext(OrgTreeRuntimeContext);
  if (!runtime) {
    // 开发期接线错误(行组件脱离 OrgTree 单独渲染); 这个文件受"界面文案必须走 i18n"的护栏, 因此用英文。
    throw new Error("OrgTreeItem must render inside OrgTree.");
  }
  return runtime;
}

/** 一行部门及其子层; 子层由自己递归渲染, 因此上层重渲染不会重新走一遍整棵树。 */
export const OrgTreeItem = memo(function OrgTreeItem({ node, depth }: { node: OrgTreeNode; depth: number }) {
  const { t } = useI18n();
  const runtime = useOrgTreeRuntime();
  const { rowStates } = runtime;
  const state = useSyncExternalStore(rowStates.subscribe, () => rowStates.readState(node.dept_id));

  if (!runtime.visibleDeptIds.has(node.dept_id)) {
    return null;
  }

  const label = runtime.labelFor(node);
  const hasChildren = node.children.length > 0;
  const showChildren = hasChildren && (state.expanded || state.exiting);

  return (
    <div
      ref={(element) => {
        runtime.registerItem(node.dept_id, element);
      }}
      className="org-tree__item"
      role="treeitem"
      aria-expanded={hasChildren ? state.expanded : undefined}
      aria-selected={state.selected}
      aria-level={depth + 1}
      tabIndex={state.active ? 0 : -1}
      data-dept-id={node.dept_id}
      // 焦点可能由浏览器给出(点行时落到最近的可聚焦祖先), 落焦点即键盘操作的落点,
      // 两者必须同步, 否则方向键会作用在上一次记录的部门上。focus 会冒泡, 只认自己这一层。
      onFocus={(event) => {
        if (event.target === event.currentTarget) {
          runtime.focusRow(node.dept_id);
        }
      }}
    >
      <div
        className="org-tree__row"
        style={{ "--org-tree-depth": depth } as CSSProperties}
        onClick={() => runtime.selectRow(node, state.expanded)}
      >
        {hasChildren ? (
          <button
            type="button"
            // 键盘导航走整棵树的方向键, 因此三角只是鼠标操作的把手, 不进入 tab 序列。
            tabIndex={-1}
            className="org-tree__chevron-button"
            aria-label={t(state.expanded ? "departmentGrants.tree.collapse" : "departmentGrants.tree.expand", {
              name: label,
            })}
            onClick={(event) => {
              event.stopPropagation();
              runtime.toggleRow(node, state.expanded);
            }}
          >
            <ChevronRight
              size={14}
              aria-hidden="true"
              className={cn("org-tree__chevron", state.expanded && "org-tree__chevron--expanded")}
            />
          </button>
        ) : (
          <span className="org-tree__chevron-placeholder" aria-hidden="true" />
        )}
        <TruncatedText className="org-tree__name" text={label} />
      </div>
      {showChildren ? (
        <div
          role="group"
          className={cn(
            "org-tree__children",
            state.entering && "org-tree__children--entering",
            state.exiting && "org-tree__children--exiting",
          )}
          aria-hidden={state.exiting || undefined}
          // 退场动画开始即移出可访问树。React 19 把 inert 当布尔属性。
          inert={state.exiting}
        >
          <div className="org-tree__children-body">
            {node.children.map((child) => (
              <OrgTreeItem key={child.dept_id} node={child} depth={depth + 1} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
});
