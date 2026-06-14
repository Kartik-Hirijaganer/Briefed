import { QueryClient } from '@tanstack/react-query';

import { seedDemoCache } from './fixtures';

/**
 * Error raised when a demo query misses the pre-seeded cache.
 */
export class DemoQueryCacheMissError extends Error {
  /**
   * Build a demo cache-miss error.
   */
  public constructor() {
    super('Demo query cache miss. Demo routes must be fully pre-seeded.');
    this.name = 'DemoQueryCacheMissError';
  }
}

/**
 * Singleton QueryClient used only under `/demo`.
 */
export const demoQueryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: Infinity,
      gcTime: Infinity,
      retry: false,
      refetchOnMount: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      queryFn: () => {
        throw new DemoQueryCacheMissError();
      },
    },
    mutations: {
      retry: false,
    },
  },
});

seedDemoCache(demoQueryClient);
