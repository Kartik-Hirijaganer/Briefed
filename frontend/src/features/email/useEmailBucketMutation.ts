import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { enqueueMutation } from '../../offline/mutations';

/**
 * Payload for a user-driven email bucket override.
 */
export interface EmailBucketMutationInput {
  /** Row being moved. */
  readonly email: Schemas['EmailRow'];
  /** Destination bucket. */
  readonly bucket: Schemas['EmailRow']['bucket'];
}

/**
 * Offline-aware email bucket mutation used by swipe gestures.
 *
 * @returns TanStack mutation for bucket changes.
 */
export function useEmailBucketMutation(): ReturnType<
  typeof useMutation<void, Error, EmailBucketMutationInput>
> {
  const online = useOnlineStatus();
  const queryClient = useQueryClient();

  return useMutation<void, Error, EmailBucketMutationInput>({
    mutationFn: async (input) => {
      if (!online) {
        await enqueueMutation({
          type: 'email_bucket_update',
          emailId: input.email.id,
          bucket: input.bucket,
        });
        return;
      }
      unwrap(
        await api.PATCH('/api/v1/emails/{email_id}/bucket', {
          params: { path: { email_id: input.email.id } },
          body: { bucket: input.bucket },
        }),
      );
    },
    onMutate: (input) => {
      updateEmailLists(input.email.id, input.bucket, queryClient);
    },
    onSuccess: (_data, input) => {
      if (!online) return;
      void queryClient.invalidateQueries({ queryKey: ['emails', input.email.bucket] });
      void queryClient.invalidateQueries({ queryKey: ['emails', input.bucket] });
      void queryClient.invalidateQueries({ queryKey: ['digest-today'] });
    },
  });
}

function updateEmailLists(
  emailId: string,
  bucket: Schemas['EmailRow']['bucket'],
  queryClient: ReturnType<typeof useQueryClient>,
): void {
  queryClient.setQueriesData<Schemas['EmailsListResponse']>(
    { queryKey: ['emails'] },
    (current) => {
      if (!current) return current;
      const nextEmails = current.emails
        .filter((email) => email.id !== emailId || email.bucket === bucket)
        .map((email) => (email.id === emailId ? { ...email, bucket } : email));
      const removed = current.emails.length - nextEmails.length;
      return {
        ...current,
        emails: nextEmails,
        total: Math.max(current.total - removed, 0),
      };
    },
  );
}
