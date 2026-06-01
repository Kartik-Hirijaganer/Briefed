import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { Alert, Button, Card, ErrorState, Field, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';

type Schedule = Schemas['UserSchedule'];
type SchedulePatch = Schemas['UserSchedulePatchRequest'];
type ScheduleFrequency = Schedule['schedule_frequency'];

const FREQUENCY_OPTIONS: ReadonlyArray<{
  readonly value: ScheduleFrequency;
  readonly label: string;
  readonly slots: number;
}> = [
  { value: 'once_daily', label: 'Once a day', slots: 1 },
  { value: 'twice_daily', label: 'Twice a day', slots: 2 },
  { value: 'disabled', label: 'Disabled', slots: 0 },
];

const FORM_CONTROL_CLASS =
  'h-[var(--control-height)] rounded-[var(--radius-md)] border border-border-strong ' +
  'bg-bg-surface px-3 text-sm focus-visible:border-accent focus-visible:outline-none ' +
  'focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]';

/**
 * Schedule settings (`/settings/schedule`). Reads and writes the dedicated
 * schedule API instead of the legacy preferences digest-hour field.
 *
 * @returns The rendered schedule form.
 */
export default function SchedulePage(): JSX.Element {
  const queryClient = useQueryClient();
  const scheduleQuery = useQuery({
    queryKey: ['profile', 'schedule'],
    queryFn: async () => unwrap(await api.GET('/api/v1/profile/me/schedule')),
  });
  const patch = useMutation({
    mutationFn: async (body: SchedulePatch) =>
      unwrap(await api.PATCH('/api/v1/profile/me/schedule', { body })),
    onSuccess: (next) => {
      queryClient.setQueryData(['profile', 'schedule'], next);
    },
  });

  if (scheduleQuery.isPending) return <Skeleton shape="block" />;
  if (scheduleQuery.isError) {
    return (
      <ErrorState
        title="Could not load schedule"
        detail={scheduleQuery.error instanceof Error ? scheduleQuery.error.message : undefined}
      />
    );
  }
  if (!scheduleQuery.data) return <Skeleton shape="block" />;

  return (
    <ScheduleForm
      schedule={scheduleQuery.data}
      pending={patch.isPending}
      error={patch.error}
      onSave={(body) => patch.mutate(body)}
    />
  );
}

interface ScheduleFormProps {
  readonly schedule: Schedule;
  readonly pending: boolean;
  readonly error: Error | null;
  readonly onSave: (body: SchedulePatch) => void;
}

/**
 * Compact schedule editor with cadence, local slots, and timezone.
 *
 * @param props - Component props.
 * @returns The rendered form.
 */
function ScheduleForm(props: ScheduleFormProps): JSX.Element {
  const { schedule, pending, error, onSave } = props;
  const [frequency, setFrequency] = useState<ScheduleFrequency>(schedule.schedule_frequency);
  const [times, setTimes] = useState<string[]>([...schedule.schedule_times_local]);
  const [timezone, setTimezone] = useState<string>(schedule.schedule_timezone);
  const timezones = useMemo(listTimezones, []);
  const nextRun = schedule.next_run_at_utc ? new Date(schedule.next_run_at_utc) : null;

  const onFrequencyChange = (next: ScheduleFrequency): void => {
    const required = FREQUENCY_OPTIONS.find((option) => option.value === next)?.slots ?? 0;
    const nextTimes = padSlots(times, required);
    setFrequency(next);
    setTimes(nextTimes);
    onSave({ schedule_frequency: next, schedule_times_local: nextTimes });
  };

  const onTimeChange = (index: number, next: string): void => {
    const nextTimes = [...times];
    nextTimes[index] = next;
    setTimes(nextTimes);
    onSave({ schedule_times_local: nextTimes });
  };

  const onTimezoneChange = (next: string): void => {
    setTimezone(next);
    onSave({ schedule_timezone: next });
  };

  return (
    <section className="flex flex-col gap-4">
      {error ? (
        <Alert tone="danger" title="Could not save schedule">
          <p>{error.message}</p>
        </Alert>
      ) : null}

      <Card className="flex flex-col gap-4">
        <header className="max-w-[var(--measure)]">
          <h2 className="text-lg font-semibold text-fg">Automatic scan schedule</h2>
          <p className="text-sm text-fg-muted">
            Schedule controls when Briefed scans unread Gmail across connected accounts.
          </p>
        </header>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium text-fg">Frequency</legend>
            {FREQUENCY_OPTIONS.map((option) => (
              <label key={option.value} className="flex items-center gap-2 text-sm text-fg">
                <input
                  type="radio"
                  name="schedule-frequency"
                  checked={frequency === option.value}
                  disabled={pending}
                  onChange={() => onFrequencyChange(option.value)}
                />
                {option.label}
              </label>
            ))}
          </fieldset>

          <Field label="Local time slots">
            <div className="flex flex-wrap gap-2">
              {frequency === 'disabled' ? (
                <span className="flex h-[var(--control-height)] items-center text-sm text-fg-muted">
                  Disabled
                </span>
              ) : (
                times.map((time, index) => (
                  <input
                    key={index}
                    type="time"
                    value={time}
                    disabled={pending}
                    onChange={(event) => onTimeChange(index, event.target.value)}
                    className={FORM_CONTROL_CLASS}
                  />
                ))
              )}
            </div>
          </Field>

          <Field label="Timezone">
            <select
              value={timezone}
              disabled={pending}
              onChange={(event) => onTimezoneChange(event.target.value)}
              className={`${FORM_CONTROL_CLASS} w-full`}
            >
              {timezones.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-fg-muted">
          <p>
            Next run:{' '}
            <span className="font-mono">
              {nextRun ? nextRun.toLocaleString() : 'not scheduled'}
            </span>
          </p>
          <Button
            variant="secondary"
            size="sm"
            disabled={pending}
            onClick={() =>
              onSave({
                schedule_frequency: frequency,
                schedule_times_local: times,
                schedule_timezone: timezone,
              })
            }
          >
            Save schedule
          </Button>
        </div>
      </Card>
    </section>
  );
}

/**
 * Pad schedule slots to the count required by a cadence.
 *
 * @param slots - Existing time slot values.
 * @param required - Required slot count.
 * @returns A normalized slot list.
 */
function padSlots(slots: readonly string[], required: number): string[] {
  const defaults = ['08:00', '18:00'];
  const next = [...slots];
  if (required === 0) return [];
  while (next.length < required) next.push(defaults[next.length] ?? '12:00');
  return next.slice(0, required);
}

/**
 * Return browser-supported timezones with a small fallback set.
 *
 * @returns Sorted IANA timezone names.
 */
function listTimezones(): string[] {
  const supported =
    typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
  if (supported.length === 0) {
    return ['UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London'];
  }
  return [...supported].sort();
}
