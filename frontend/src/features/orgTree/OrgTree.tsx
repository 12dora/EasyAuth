import { ChevronRight } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import { useGroupTransitionKeys } from "../../pages/portal/components/useGroupTransitionKeys";

/** 部门树节点; 与 `GET /console/api/v1/departments/tree` 的 `root` 同形。 */
export interface OrgTreeNode {
  dept_id: string;
  name: string;
  member_count: number;
  children: OrgTreeNode[];
}

export interface OrgTreeProps {
  root: OrgTreeNode;
  selectedDeptId: string;
  /** 受控展开集合; 过滤命中时祖先额外自动展开(不写回调用方状态)。 */
  expandedDeptIds: string[];
  onSelect: (deptId: string) => void;
  onExpandedChange: (deptIds: string[]) => void;
  /** 按部门名过滤; 空串表示不过滤。搜索框由调用方渲染。 */
  filter?: string;
  /**
   * 行文案。缺省用 `node.name`; 名字可能为空(钉钉根部门)的场景由调用方传入兜底文案,
   * 组件本身不认识任何业务口径。过滤与无障碍名同样按这份文案走。
   */
  labelFor?: (node: OrgTreeNode) => string;
}

function nodeName(node: OrgTreeNode): string {
  return node.name;
}

interface FlatRow {
  node: OrgTreeNode;
  depth: number;
  parentDeptId: string;
}

/**
 * 受控的部门树。
 *
 * 键盘按 WAI-ARIA tree 约定: 上下移动、右展开(已展开则进入首个子节点)、
 * 左收起(已收起则回到父节点)、Enter 选中; 焦点用 roving tabindex, 整棵树只有一个
 * tab 停靠点。展开/收起动画见 `styles/features/org-tree.css`。
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
  const keyword = filter.trim().toLowerCase();

  const visibleDeptIds = useMemo(() => collectVisibleDeptIds(root, keyword, labelFor), [root, keyword, labelFor]);
  const autoExpandedDeptIds = useMemo(
    () => collectMatchAncestorIds(root, keyword, labelFor),
    [root, keyword, labelFor],
  );
  // 过滤命中时祖先必须展开才看得到匹配项; 这是渲染期的派生值, 不回写受控状态,
  // 清空搜索后展开集合原样回到用户自己的选择。
  const effectiveExpandedIds = useMemo(
    () => [...expandedDeptIds, ...autoExpandedDeptIds.filter((deptId) => !expandedDeptIds.includes(deptId))],
    [expandedDeptIds, autoExpandedDeptIds],
  );

  const enteringDeptIds = useGroupTransitionKeys(effectiveExpandedIds, "entering");
  const exitingDeptIds = useGroupTransitionKeys(effectiveExpandedIds, "exiting");

  const rows = useMemo(
    () => flattenRows(root, effectiveExpandedIds, visibleDeptIds),
    [root, effectiveExpandedIds, visibleDeptIds],
  );

  const [focusedDeptId, setFocusedDeptId] = useState("");
  const itemsByDeptId = useRef(new Map<string, HTMLDivElement>());

  // 焦点落点: 用户上次落焦的行 > 当前选中行 > 第一行。行被过滤掉或收起时自动回退。
  const activeDeptId =
    rows.find((row) => row.node.dept_id === focusedDeptId)?.node.dept_id ??
    rows.find((row) => row.node.dept_id === selectedDeptId)?.node.dept_id ??
    rows[0]?.node.dept_id ??
    "";

  const moveFocusTo = (deptId: string | undefined) => {
    if (!deptId) {
      return;
    }
    setFocusedDeptId(deptId);
    itemsByDeptId.current.get(deptId)?.focus();
  };

  const setExpanded = (deptId: string, expanded: boolean) => {
    if (expanded) {
      if (!expandedDeptIds.includes(deptId)) {
        onExpandedChange([...expandedDeptIds, deptId]);
      }
      return;
    }
    onExpandedChange(expandedDeptIds.filter((current) => current !== deptId));
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = rows.findIndex((row) => row.node.dept_id === activeDeptId);
    if (index === -1) {
      return;
    }
    const row = rows[index];
    const deptId = row.node.dept_id;
    const hasChildren = row.node.children.length > 0;
    const expanded = effectiveExpandedIds.includes(deptId);

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        moveFocusTo(rows[index + 1]?.node.dept_id);
        return;
      case "ArrowUp":
        event.preventDefault();
        moveFocusTo(rows[index - 1]?.node.dept_id);
        return;
      case "ArrowRight":
        event.preventDefault();
        if (!hasChildren) {
          return;
        }
        if (expanded) {
          moveFocusTo(rows[index + 1]?.node.dept_id);
          return;
        }
        setExpanded(deptId, true);
        return;
      case "ArrowLeft":
        event.preventDefault();
        if (hasChildren && expanded) {
          setExpanded(deptId, false);
          return;
        }
        moveFocusTo(row.parentDeptId || undefined);
        return;
      case "Enter":
        event.preventDefault();
        setFocusedDeptId(deptId);
        onSelect(deptId);
        return;
      default:
    }
  };

  const renderNode = (node: OrgTreeNode, depth: number): ReactNode => {
    if (!visibleDeptIds.has(node.dept_id)) {
      return null;
    }
    const hasChildren = node.children.length > 0;
    const expanded = effectiveExpandedIds.includes(node.dept_id);
    const entering = enteringDeptIds.includes(node.dept_id);
    const exiting = exitingDeptIds.includes(node.dept_id);
    const showChildren = hasChildren && (expanded || exiting);

    return (
      <div
        key={node.dept_id}
        ref={(element) => {
          if (element) {
            itemsByDeptId.current.set(node.dept_id, element);
          } else {
            itemsByDeptId.current.delete(node.dept_id);
          }
        }}
        className="org-tree__item"
        role="treeitem"
        aria-expanded={hasChildren ? expanded : undefined}
        aria-selected={node.dept_id === selectedDeptId}
        aria-level={depth + 1}
        tabIndex={node.dept_id === activeDeptId ? 0 : -1}
        data-dept-id={node.dept_id}
        // 焦点可能由浏览器给出(点行时落到最近的可聚焦祖先), 落焦点即键盘操作的落点,
        // 两者必须同步, 否则方向键会作用在上一次记录的部门上。focus 会冒泡, 只认自己这一层。
        onFocus={(event) => {
          if (event.target === event.currentTarget) {
            setFocusedDeptId(node.dept_id);
          }
        }}
      >
        <div
          className="org-tree__row"
          style={{ "--org-tree-depth": depth } as CSSProperties}
          onClick={() => {
            moveFocusTo(node.dept_id);
            onSelect(node.dept_id);
          }}
        >
          {hasChildren ? (
            <button
              type="button"
              // 键盘导航走整棵树的方向键, 因此三角只是鼠标操作的把手, 不进入 tab 序列。
              tabIndex={-1}
              className="org-tree__chevron-button"
              aria-label={t(expanded ? "departmentGrants.tree.collapse" : "departmentGrants.tree.expand", {
                name: labelFor(node),
              })}
              onClick={(event) => {
                event.stopPropagation();
                // 鼠标点三角同样是在操作这一行: 焦点跟过来, 紧接着的方向键/回车才作用在它身上。
                moveFocusTo(node.dept_id);
                setExpanded(node.dept_id, !expanded);
              }}
            >
              <ChevronRight
                size={14}
                aria-hidden="true"
                className={cn("org-tree__chevron", expanded && "org-tree__chevron--expanded")}
              />
            </button>
          ) : (
            <span className="org-tree__chevron-placeholder" aria-hidden="true" />
          )}
          <span className="org-tree__name">{labelFor(node)}</span>
          <span className="org-tree__count">
            {t("departmentGrants.tree.memberCount", { count: node.member_count })}
          </span>
        </div>
        {showChildren ? (
          <div
            role="group"
            className={cn(
              "org-tree__children",
              entering && "org-tree__children--entering",
              exiting && "org-tree__children--exiting",
            )}
            aria-hidden={exiting || undefined}
            // 退场动画开始即移出可访问树。React 19 把 inert 当布尔属性。
            inert={exiting}
          >
            <div className="org-tree__children-body">
              {node.children.map((child) => renderNode(child, depth + 1))}
            </div>
          </div>
        ) : null}
      </div>
    );
  };

  if (!visibleDeptIds.has(root.dept_id)) {
    return <p className="org-tree__empty">{t("departmentGrants.tree.noMatch")}</p>;
  }

  return (
    <div className="org-tree" role="tree" aria-label={t("departmentGrants.tree.ariaLabel")} onKeyDown={handleKeyDown}>
      {renderNode(root, 0)}
    </div>
  );
}

function nodeMatches(node: OrgTreeNode, keyword: string, labelFor: (node: OrgTreeNode) => string): boolean {
  return keyword === "" || labelFor(node).toLowerCase().includes(keyword);
}

/** 自身命中或有后代命中的节点; 过滤为空时即全部节点。 */
function collectVisibleDeptIds(
  root: OrgTreeNode,
  keyword: string,
  labelFor: (node: OrgTreeNode) => string,
): Set<string> {
  const visible = new Set<string>();

  const walk = (node: OrgTreeNode): boolean => {
    const childMatched = node.children.map(walk).some(Boolean);
    const matched = nodeMatches(node, keyword, labelFor) || childMatched;
    if (matched) {
      visible.add(node.dept_id);
    }
    return matched;
  };

  walk(root);
  return visible;
}

/** 命中节点的祖先(不含命中节点自身); 过滤为空时无自动展开。 */
function collectMatchAncestorIds(
  root: OrgTreeNode,
  keyword: string,
  labelFor: (node: OrgTreeNode) => string,
): string[] {
  if (keyword === "") {
    return [];
  }
  const ancestors: string[] = [];

  const walk = (node: OrgTreeNode): boolean => {
    const childMatched = node.children.map(walk).some(Boolean);
    if (childMatched) {
      ancestors.push(node.dept_id);
    }
    return nodeMatches(node, keyword, labelFor) || childMatched;
  };

  walk(root);
  return ancestors;
}

/** 当前可见(未被过滤掉且祖先均已展开)的行, 按视觉顺序; 键盘导航据此移动。 */
function flattenRows(root: OrgTreeNode, expandedDeptIds: string[], visibleDeptIds: Set<string>): FlatRow[] {
  const rows: FlatRow[] = [];

  const walk = (node: OrgTreeNode, depth: number, parentDeptId: string) => {
    if (!visibleDeptIds.has(node.dept_id)) {
      return;
    }
    rows.push({ node, depth, parentDeptId });
    if (!expandedDeptIds.includes(node.dept_id)) {
      return;
    }
    for (const child of node.children) {
      walk(child, depth + 1, node.dept_id);
    }
  };

  walk(root, 0, "");
  return rows;
}
