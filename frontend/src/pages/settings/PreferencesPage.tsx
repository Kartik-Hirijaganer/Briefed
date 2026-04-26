import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Card, ErrorState, Field, Skeleton, Switch } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { enqueueMutation } from '../../offline/mutations';

/**
 * Global user preferences (plan §19.16 §2 auto-execution toggle,
 * plus the opt-in redaction + secure-offline toggles from §11).
 *
 * @returns The rendered preferences form.
 */
export default function PreferencesPage(): JSX.Element {
  const client = useQueryClient();
  const online = useOnlineStatus();
  const preferencesQuery = useQuery({
    queryKey: ['preferences'],
    queryFn: async () => unwrap(await api.GET('/api/v1/preferences')),
  });

  const patch = useMutation({
    mutationFn: async (body: Schemas['PreferencesPatchRequest']) => {
      if (!online) {
        await enqueueMutation({ type: 'preferences_patch', body });
        return body;
      }
      return unwrap(await api.PATCH('/api/v1/preferences', { body }));
    },
    onMutate: (body) => {
      client.setQueryData<Schemas['UserPreferences']>(['preferences'], (current) =>
        current ? applyPreferencesPatch(current, body) : current,
      );
    },
    onSuccess: () => {
      if (online) void client.invalidateQueries({ queryKey: ['preferences'] });
    },
  });

  if (preferencesQuery.isPending) return <Skeleton shape="block" />;
  if (preferencesQuery.isError) {
    return (
      <ErrorState
        title="Could not load preferences"
        detail={
          preferencesQuery.error instanceof Error ? preferencesQuery.error.message : undefined
        }
      />
    );
  }
  const prefs = preferencesQuery.data;
  if (!prefs) return <Skeleton shape="block" />;

  return (
    <section className="flex flex-col gap-4">
      <Card className="flex flex-col gap-3">
        <Field
          label="Automatic daily scans"
          description="Briefed scans your connected Gmail accounts on the schedule below. Turn off to run only manually."
        >
          <Switch
            checked={prefs.auto_execution_enabled}
            onCheckedChange={(next) => patch.mutate({ auto_execution_enabled: next })}
            ariaLabel="Automatic daily scans"
          />
        </Field>
      </Card>
      <Card className="flex flex-col gap-3">
        <Field
          label="Redact PII before sending to the LLM"
          description="Off by default for personal use. Turn on if you forward work mail that contains customer data."
        >
          <Switch
            checked={prefs.redact_pii}
            onCheckedChange={(next) => patch.mutate({ redact_pii: next })}
            ariaLabel="Redact PII before sending to the LLM"
          />
        </Field>
      </Card>
      <Card className="flex flex-col gap-3">
        <Field
          label="Secure offline mode"
          description="Encrypts queued mutations and cached summaries in IndexedDB with a passcode. Re-prompts after inactivity."
        >
          <Switch
            checked={prefs.secure_offline_mode}
            onCheckedChange={(next) => patch.mutate({ secure_offline_mode: next })}
            ariaLabel="Enable secure offline mode"
          />
        </Field>
      </Card>
    </section>
  );
}

function applyPreferencesPatch(
  current: Schemas['UserPreferences'],
  body: Schemas['PreferencesPatchRequest'],
): Schemas['UserPreferences'] {
  return {
    auto_execution_enabled: body.auto_execution_enabled ?? current.auto_execution_enabled,
    digest_send_hour_utc: body.digest_send_hour_utc ?? current.digest_send_hour_utc,
    redact_pii: body.redact_pii ?? current.redact_pii,
    secure_offline_mode: body.secure_offline_mode ?? current.secure_offline_mode,
    retention_policy_json: body.retention_policy_json ?? current.retention_policy_json,
  };
}
