/** 管理目录三类表单的编辑状态、弹窗状态与保存操作。 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type { AppScopeItem } from "../../../../lib/domain";
import { invalidateAppCatalogQueries } from "../invalidateAppQueries";
import {
  emptyGroupForm,
  emptyPermissionForm,
  emptyScopeForm,
  groupPayload,
  permissionPayload,
  type CatalogDialog,
  type PermissionForm,
  type PermissionGroupForm,
  type ScopeForm,
} from "./catalogModel";

export function useCatalogForms(appKey: string) {
  const [permissionForm, setPermissionForm] = useState<PermissionForm>(emptyPermissionForm);
  const [editingPermissionKey, setEditingPermissionKey] = useState("");
  const [scopeForm, setScopeForm] = useState<ScopeForm>(emptyScopeForm);
  const [editingScopeKey, setEditingScopeKey] = useState("");
  const [groupForm, setGroupForm] = useState<PermissionGroupForm>(emptyGroupForm);
  const [editingGroupKey, setEditingGroupKey] = useState("");
  const [activeDialog, setActiveDialog] = useState<CatalogDialog>(null);
  const resetPermission = () => {
    setPermissionForm(emptyPermissionForm);
    setEditingPermissionKey("");
    setActiveDialog(null);
  };
  const resetScope = () => {
    setScopeForm(emptyScopeForm);
    setEditingScopeKey("");
    setActiveDialog(null);
  };
  const resetGroup = () => {
    setGroupForm(emptyGroupForm);
    setEditingGroupKey("");
    setActiveDialog(null);
  };

  return {
    permissionForm, setPermissionForm, editingPermissionKey, setEditingPermissionKey,
    scopeForm, setScopeForm, editingScopeKey, setEditingScopeKey,
    groupForm, setGroupForm, editingGroupKey, setEditingGroupKey,
    activeDialog, setActiveDialog,
    savePermissionMutation: useSavePermission(appKey, editingPermissionKey, permissionForm, resetPermission),
    saveScopeMutation: useSaveScope(appKey, editingScopeKey, scopeForm, resetScope),
    toggleScopeMutation: useToggleScope(appKey),
    saveGroupMutation: useSaveGroup(appKey, editingGroupKey, groupForm, resetGroup),
  };
}

function useSavePermission(appKey: string, editingKey: string, form: PermissionForm, onSuccess: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest(`/console/api/v1/apps/${appKey}/permissions${editingKey ? `/${editingKey}` : ""}`, {
      method: editingKey ? "PATCH" : "POST",
      body: permissionPayload(form),
    }),
    onSuccess: () => {
      onSuccess();
      invalidateAppCatalogQueries(queryClient, appKey);
    },
  });
}

function useSaveScope(appKey: string, editingKey: string, form: ScopeForm, onSuccess: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest(`/console/api/v1/apps/${appKey}/scopes${editingKey ? `/${editingKey}` : ""}`, {
      method: editingKey ? "PATCH" : "POST",
      body: { ...form } satisfies JsonObject,
    }),
    onSuccess: () => {
      onSuccess();
      invalidateAppCatalogQueries(queryClient, appKey);
    },
  });
}

function useToggleScope(appKey: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scope: AppScopeItem) => apiRequest(`/console/api/v1/apps/${appKey}/scopes/${scope.key}`, {
      method: "PATCH",
      body: { ...scope, is_active: !scope.is_active } satisfies JsonObject,
    }),
    onSuccess: () => {
      invalidateAppCatalogQueries(queryClient, appKey);
    },
  });
}

function useSaveGroup(appKey: string, editingKey: string, form: PermissionGroupForm, onSuccess: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest(`/console/api/v1/apps/${appKey}/permission-groups${editingKey ? `/${editingKey}` : ""}`, {
      method: editingKey ? "PATCH" : "POST",
      body: groupPayload(form),
    }),
    onSuccess: () => {
      onSuccess();
      invalidateAppCatalogQueries(queryClient, appKey);
    },
  });
}
