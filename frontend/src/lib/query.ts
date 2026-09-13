import {
  QueryClient,
  useMutation,
  useQueryClient,
  type QueryKey,
  type UseMutationOptions,
} from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * 控制台/门户弹窗变更的共用包装: 成功时先跑调用方 onSuccess, 再按 queryKey 失效缓存;
 * 失败留给 MutationErrorBanner。
 */
export function useApiMutation<TData = unknown, TError = Error, TVariables = void, TContext = unknown>(
  options: UseMutationOptions<TData, TError, TVariables, TContext> & {
    invalidateQueryKeys?: QueryKey[];
    invalidate?: (client: QueryClient) => void;
  },
) {
  const client = useQueryClient();
  const { invalidateQueryKeys, invalidate, onSuccess, ...rest } = options;
  return useMutation({
    ...rest,
    onSuccess: (data, variables, onMutateResult, context) => {
      onSuccess?.(data, variables, onMutateResult, context);
      const tasks: Promise<unknown>[] = [];
      if (invalidateQueryKeys) {
        for (const queryKey of invalidateQueryKeys) {
          tasks.push(client.invalidateQueries({ queryKey }));
        }
      }
      invalidate?.(client);
      return tasks.length > 0 ? Promise.all(tasks) : undefined;
    },
  });
}
