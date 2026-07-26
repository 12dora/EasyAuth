import type { QueryClient } from "@tanstack/react-query";

export function invalidateAppDerivedQueries(queryClient: QueryClient, appKey: string): void {
  void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey], exact: true });
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "configuration-status"], exact: true });
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "capabilities"], exact: true });
}

export function invalidateAppCatalogQueries(queryClient: QueryClient, appKey: string): void {
  invalidateAppDerivedQueries(queryClient, appKey);
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "authorization-groups"] });
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permission-groups"] });
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permissions"] });
  void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey, "permission-tree"] });
  void queryClient.invalidateQueries({ queryKey: ["portal", "request-catalog"] });
}
