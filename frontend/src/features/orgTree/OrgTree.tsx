import { ChevronRight } from "lucide-react";
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { CSSProperties, KeyboardEvent } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import { useGroupTransitionKeys } from "../../pages/portal/components/useGroupTransitionKeys";

/** 部门树节点; 与 `GET /console/api/v1/departments/tree` 的 `root` 同形。 */
export interface OrgTreeNode {
  dept_id: string;
  name: string;
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

/** 单行的易变状态; 行组件只订阅自己这一份。 */
interface OrgTreeRowState {
  selected: boolean;
  /** roving tabindex 的落点。 */
  active: boolean;
  expanded: boolean;
  entering: boolean;
  exiting: boolean;
}

interface OrgTreeRowStateInput {
  selectedDeptId: string;
  activeDeptId: string;
  expandedDeptIds: string[];
  enteringDeptIds: string[];
  exitingDeptIds: string[];
}

/**
 * 行状态的外部存储。
 *
 * 选中态如果顺着 props/context 往下发, 每换一个部门整棵树都要重渲染, 选中就会跟着数据量变慢。
 * 这里让每一行只订阅自己那一份状态: 换选中只有"旧选中行"和"新选中行"重渲染, 其余行连
 * `React.memo` 的比较都不需要跨过。快照必须是稳定引用, 否则 useSyncExternalStore 会判定每次读取都在变。
 */
function createOrgTreeRowStateStore(initial: OrgTreeRowStateInput) {
  let input = initial;
  const listeners = new Set<() => void>();
  const states = new Map<string, OrgTreeRowState>();

  const readState = (deptId: string): OrgTreeRowState => {
    const next: OrgTreeRowState = {
      selected: input.selectedDeptId === deptId,
      active: input.activeDeptId === deptId,
      expanded: input.expandedDeptIds.includes(deptId),
      entering: input.enteringDeptIds.includes(deptId),
      exiting: input.exitingDeptIds.includes(deptId),
    };
    const current = states.get(deptId);
    if (current && rowStatesAreEqual(current, next)) {
      return current;
    }
    states.set(deptId, next);
    return next;
  };

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    readState,
    update(next: OrgTreeRowStateInput) {
      input = next;
      for (const listener of [...listeners]) {
        listener();
      }
    },
  };
}

type OrgTreeRowStateStore = ReturnType<typeof createOrgTreeRowStateStore>;

function rowStatesAreEqual(left: OrgTreeRowState, right: OrgTreeRowState): boolean {
  return (
    left.selected === right.selected &&
    left.active === right.active &&
    left.expanded === right.expanded &&
    left.entering === right.entering &&
    left.exiting === right.exiting
  );
}

/** 行组件要用到的、整棵树共享且引用稳定的东西; 变了才值得让所有行重渲染(换过滤、换根)。 */
interface OrgTreeRuntime {
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

const OrgTreeRuntimeContext = createContext<OrgTreeRuntime | null>(null);

function useOrgTreeRuntime(): OrgTreeRuntime {
  const runtime = useContext(OrgTreeRuntimeContext);
  if (!runtime) {
    throw new Error("OrgTreeItem 只能渲染在 OrgTree 内部。");
  }
  return runtime;
}

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

  // 行上的事件回调必须自始至终是同一份引用, 否则 runtime 一变整棵树都要重渲染;
  // 它们要读的最新 props 走这份 ref —— 事件只在提交之后触发, 提交后再写是安全的。
  const latestPropsRef = useRef({ expandedDeptIds, onSelect, onExpandedChange });
  useLayoutEffect(() => {
    latestPropsRef.current = { expandedDeptIds, onSelect, onExpandedChange };
  });

  const focusItem = useCallback((deptId: string) => {
    setFocusedDeptId(deptId);
    itemsByDeptId.current.get(deptId)?.focus();
  }, []);

  const setExpanded = useCallback((deptId: string, expanded: boolean) => {
    const { expandedDeptIds: current, onExpandedChange: change } = latestPropsRef.current;
    if (expanded) {
      if (!current.includes(deptId)) {
        change([...current, deptId]);
      }
      return;
    }
    change(current.filter((item) => item !== deptId));
  }, []);

  const selectRow = useCallback(
    (node: OrgTreeNode, expanded: boolean) => {
      // 鼠标点行同样是在操作这一行: 焦点跟过来, 紧接着的方向键/回车才作用在它身上。
      focusItem(node.dept_id);
      latestPropsRef.current.onSelect(node.dept_id);
      if (node.children.length > 0) {
        setExpanded(node.dept_id, !expanded);
      }
    },
    [focusItem, setExpanded],
  );

  const toggleRow = useCallback(
    (node: OrgTreeNode, expanded: boolean) => {
      focusItem(node.dept_id);
      setExpanded(node.dept_id, !expanded);
    },
    [focusItem, setExpanded],
  );

  const registerItem = useCallback((deptId: string, element: HTMLDivElement | null) => {
    if (element) {
      itemsByDeptId.current.set(deptId, element);
      return;
    }
    itemsByDeptId.current.delete(deptId);
  }, []);

  const rowStateInput = useMemo<OrgTreeRowStateInput>(
    () => ({
      selectedDeptId,
      activeDeptId,
      expandedDeptIds: effectiveExpandedIds,
      enteringDeptIds,
      exitingDeptIds,
    }),
    [selectedDeptId, activeDeptId, effectiveExpandedIds, enteringDeptIds, exitingDeptIds],
  );
  const [rowStates] = useState(() => createOrgTreeRowStateStore(rowStateInput));
  // 布局阶段推送: 订阅到变化的行在浏览器绘制之前就重渲染完, 选中态不会晚一帧。
  useLayoutEffect(() => {
    rowStates.update(rowStateInput);
  }, [rowStates, rowStateInput]);

  const runtime = useMemo<OrgTreeRuntime>(
    () => ({
      labelFor,
      visibleDeptIds,
      rowStates,
      selectRow,
      toggleRow,
      focusRow: setFocusedDeptId,
      registerItem,
    }),
    [labelFor, visibleDeptIds, rowStates, selectRow, toggleRow, registerItem],
  );

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = rows.findIndex((row) => row.node.dept_id === activeDeptId);
    if (index === -1) {
      return;
    }
    const row = rows[index];
    const deptId = row.node.dept_id;
    const hasChildren = row.node.children.length > 0;
    const expanded = effectiveExpandedIds.includes(deptId);
    const moveFocusTo = (nextDeptId: string | undefined) => {
      if (nextDeptId) {
        focusItem(nextDeptId);
      }
    };

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

  if (!visibleDeptIds.has(root.dept_id)) {
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

/** 一行部门及其子层; 子层由自己递归渲染, 因此上层重渲染不会重新走一遍整棵树。 */
const OrgTreeItem = memo(function OrgTreeItem({ node, depth }: { node: OrgTreeNode; depth: number }) {
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
        <span className="org-tree__name">{label}</span>
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
