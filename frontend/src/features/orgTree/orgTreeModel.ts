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

export function nodeName(node: OrgTreeNode): string {
  return node.name;
}

export interface FlatRow {
  node: OrgTreeNode;
  depth: number;
  parentDeptId: string;
}

/** 单行的易变状态; 行组件只订阅自己这一份。 */
export interface OrgTreeRowState {
  selected: boolean;
  /** roving tabindex 的落点。 */
  active: boolean;
  expanded: boolean;
  entering: boolean;
  exiting: boolean;
}

export interface OrgTreeRowStateInput {
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
export function createOrgTreeRowStateStore(initial: OrgTreeRowStateInput) {
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

export type OrgTreeRowStateStore = ReturnType<typeof createOrgTreeRowStateStore>;

function rowStatesAreEqual(left: OrgTreeRowState, right: OrgTreeRowState): boolean {
  return (
    left.selected === right.selected &&
    left.active === right.active &&
    left.expanded === right.expanded &&
    left.entering === right.entering &&
    left.exiting === right.exiting
  );
}

function nodeMatches(node: OrgTreeNode, keyword: string, labelFor: (node: OrgTreeNode) => string): boolean {
  return keyword === "" || labelFor(node).toLowerCase().includes(keyword);
}

/** 自身命中或有后代命中的节点; 过滤为空时即全部节点。 */
export function collectVisibleDeptIds(
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
export function collectMatchAncestorIds(
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
export function flattenRows(root: OrgTreeNode, expandedDeptIds: string[], visibleDeptIds: Set<string>): FlatRow[] {
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
