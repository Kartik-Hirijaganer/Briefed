import { QueryClient } from '@tanstack/react-query';

/**
 * Shared TanStack Query client for the app. `staleTime` defaults match the
 * PWA runtime-cache contract in plan §10: digests are 60 s stale, immutable
 * summary bodies never go stale, everything else is 5 min.
 *
 * Features opt into tighter staleness via `useQuery({ staleTime })`.
 */
export const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 7 * 24 * 60 * 60 * 1000,
      retry: (failureCount: number, error: unknown): boolean => {
        const status =
          error && typeof error === 'object' && 'status' in error
            ? (error as { status: number }).status
            : undefined;
        if (status !== undefined && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
    mutations: {
      retry: false,
    },
  },
});
