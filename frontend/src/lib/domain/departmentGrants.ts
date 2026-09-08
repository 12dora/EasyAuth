/**
 * 组织授权(部门预授权)的前端契约。
 *
 * 与门户申请目录的解析同一口径: 形状不符立刻抛出中文契约错误, 不做任何字段兜底、
 * 不给缺失字段填默认值 —— 少一个字段就意味着界面会把"未知"渲染成"没有", 这里必须失败得刺眼。
 */

import type { OrgTreeNode } from "../../features/orgTree/OrgTree";
import type { GrantTermType } from "../../features/grantForm";

export type { OrgTreeNode };

export interface DepartmentTree {
  source_slug: string;
  corp_id: string;
  synced_at: string;
  root: OrgTreeNode;
}

export interface DepartmentRef {
  dept_id: string;
  name: string;
}

export interface DepartmentSummary extends DepartmentRef {
  /** 从根部门到自身的完整层级。 */
  path: DepartmentRef[];
  member_count: number;
  subtree_member_count: number;
}

export interface DepartmentGrantPolicyApp {
  app_key: string;
  name: string;
  alias: string;
}

export interface DepartmentGrantPolicyGroup {
  key: string;
  name: string;
  kind: string;
}

export interface DepartmentGrantPolicyPermission {
  key: string;
  name: string;
  scope: string;
  scope_name: string;
}

export interface DepartmentGrantPolicyActor {
  user_id: string;
  name: string;
}

export interface DepartmentGrantPolicy {
  id: number;
  app: DepartmentGrantPolicyApp;
  authorization_groups: DepartmentGrantPolicyGroup[];
  permissions: DepartmentGrantPolicyPermission[];
  grant_type: GrantTermType;
  expires_at: string | null;
  reason: string;
  /** 策略定义在哪个部门上; 与当前部门不同即为继承。 */
  defined_on: DepartmentRef;
  inherited: boolean;
  affected_user_count: number;
  created_at: string;
  updated_at: string;
  created_by: DepartmentGrantPolicyActor | null;
  updated_by: DepartmentGrantPolicyActor | null;
}

export interface DepartmentGrantPolicyList {
  department: DepartmentSummary;
  items: DepartmentGrantPolicy[];
}

export function parseDepartmentTree(value: unknown): DepartmentTree {
  const payload = contractRecord(value, "部门树");
  const tree = contractRecord(payload.data, "部门树.data");
  contractNonEmptyString(tree.source_slug, "部门树.data.source_slug");
  contractString(tree.corp_id, "部门树.data.corp_id");
  contractString(tree.synced_at, "部门树.data.synced_at");
  validateOrgTreeNode(tree.root, "部门树.data.root");
  return tree as unknown as DepartmentTree;
}

export function parseDepartmentGrantPolicies(value: unknown): DepartmentGrantPolicyList {
  const payload = contractRecord(value, "部门授权");
  const data = contractRecord(payload.data, "部门授权.data");
  validateDepartmentSummary(data.department, "部门授权.data.department");
  contractArray(data.items, "部门授权.data.items").forEach((item, index) =>
    validateDepartmentGrantPolicy(item, `部门授权.data.items[${index}]`),
  );
  return data as unknown as DepartmentGrantPolicyList;
}

function validateOrgTreeNode(value: unknown, path: string): void {
  const node = contractRecord(value, path);
  contractNonEmptyString(node.dept_id, `${path}.dept_id`);
  // 钉钉根部门在镜像里就是空名字, 展示层用「全公司」兜底(departmentDisplayName), 契约这一层只要求是字符串。
  contractString(node.name, `${path}.name`);
  contractArray(node.children, `${path}.children`).forEach((child, index) =>
    validateOrgTreeNode(child, `${path}.children[${index}]`),
  );
}

function validateDepartmentRef(value: unknown, path: string): void {
  const ref = contractRecord(value, path);
  contractNonEmptyString(ref.dept_id, `${path}.dept_id`);
  // 同上: 根部门可以没有名字。
  contractString(ref.name, `${path}.name`);
}

function validateDepartmentSummary(value: unknown, path: string): void {
  validateDepartmentRef(value, path);
  const department = contractRecord(value, path);
  contractArray(department.path, `${path}.path`).forEach((item, index) =>
    validateDepartmentRef(item, `${path}.path[${index}]`),
  );
  contractNumber(department.member_count, `${path}.member_count`);
  contractNumber(department.subtree_member_count, `${path}.subtree_member_count`);
}

function validateDepartmentGrantPolicy(value: unknown, path: string): void {
  const policy = contractRecord(value, path);
  contractNumber(policy.id, `${path}.id`);

  const app = contractRecord(policy.app, `${path}.app`);
  contractNonEmptyString(app.app_key, `${path}.app.app_key`);
  contractNonEmptyString(app.name, `${path}.app.name`);
  // 别名是可选配置, 没配时后端下发空字符串; 字段本身必须存在。
  contractString(app.alias, `${path}.app.alias`);

  contractArray(policy.authorization_groups, `${path}.authorization_groups`).forEach((item, index) => {
    const group = contractRecord(item, `${path}.authorization_groups[${index}]`);
    contractNonEmptyString(group.key, `${path}.authorization_groups[${index}].key`);
    contractNonEmptyString(group.name, `${path}.authorization_groups[${index}].name`);
    contractNonEmptyString(group.kind, `${path}.authorization_groups[${index}].kind`);
  });

  contractArray(policy.permissions, `${path}.permissions`).forEach((item, index) => {
    const permission = contractRecord(item, `${path}.permissions[${index}]`);
    contractNonEmptyString(permission.key, `${path}.permissions[${index}].key`);
    contractNonEmptyString(permission.name, `${path}.permissions[${index}].name`);
    contractNonEmptyString(permission.scope, `${path}.permissions[${index}].scope`);
    contractNonEmptyString(permission.scope_name, `${path}.permissions[${index}].scope_name`);
  });

  contractGrantType(policy.grant_type, `${path}.grant_type`);
  // 期限与到期时间必须自洽: 长期不带到期时间, 限时必须有。
  if (policy.grant_type === "timed") {
    contractNonEmptyString(policy.expires_at, `${path}.expires_at`);
  } else if (policy.expires_at !== null) {
    throw new Error(`${path}.expires_at 在长期授权下必须为 null`);
  }

  contractString(policy.reason, `${path}.reason`);
  validateDepartmentRef(policy.defined_on, `${path}.defined_on`);
  contractBoolean(policy.inherited, `${path}.inherited`);
  contractNumber(policy.affected_user_count, `${path}.affected_user_count`);
  contractNonEmptyString(policy.created_at, `${path}.created_at`);
  contractNonEmptyString(policy.updated_at, `${path}.updated_at`);
  validateActor(policy.created_by, `${path}.created_by`);
  validateActor(policy.updated_by, `${path}.updated_by`);
}

/** 操作人可能是系统写入(null), 但字段必须存在。 */
function validateActor(value: unknown, path: string): void {
  if (value === null) {
    return;
  }
  const actor = contractRecord(value, path);
  contractNonEmptyString(actor.user_id, `${path}.user_id`);
  contractString(actor.name, `${path}.name`);
}

function contractRecord(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} 必须为对象`);
  }
  return value as Record<string, unknown>;
}

function contractArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${path} 必须为数组`);
  }
  return value;
}

function contractString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new Error(`${path} 必须为字符串`);
  }
  return value;
}

function contractNonEmptyString(value: unknown, path: string): string {
  const text = contractString(value, path);
  if (text === "") {
    throw new Error(`${path} 不能为空`);
  }
  return text;
}

function contractNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} 必须为数字`);
  }
  return value;
}

function contractBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${path} 必须为布尔值`);
  }
  return value;
}

function contractGrantType(value: unknown, path: string): GrantTermType {
  if (value !== "permanent" && value !== "timed") {
    throw new Error(`${path} 必须为 permanent 或 timed`);
  }
  return value;
}
