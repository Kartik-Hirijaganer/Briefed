import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Alert, Button, Card, ErrorState, Field, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import { schedule } from '../../api/queryKeys';
import type { Schemas } from '../../api/types';
import { useDemoMode } from '../../demo/DemoModeProvider';

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

interface TimezoneOption {
  readonly value: string;
  readonly label: string;
}

const US_INDIA_TIMEZONES: ReadonlyArray<TimezoneOption> = [
  { value: 'America/New_York', label: 'US Eastern — New York' },
  { value: 'America/Chicago', label: 'US Central — Chicago' },
  { value: 'America/Denver', label: 'US Mountain — Denver' },
  { value: 'America/Phoenix', label: 'US Mountain, no DST — Phoenix' },
  { value: 'America/Los_Angeles', label: 'US Pacific — Los Angeles' },
  { value: 'America/Anchorage', label: 'US Alaska — Anchorage' },
  { value: 'Pacific/Honolulu', label: 'US Hawaii — Honolulu' },
  { value: 'Asia/Kolkata', label: 'India — Kolkata (IST)' },
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
  const { isDemo } = useDemoMode();
  const queryClient = useQueryClient();
  const scheduleQuery = useQuery({
    queryKey: schedule(),
    queryFn: async () => unwrap(await api.GET('/api/v1/profile/me/schedule')),
  });
  const patch = useMutation({
    mutationFn: async (body: SchedulePatch) =>
      unwrap(await api.PATCH('/api/v1/profile/me/schedule', { body })),
    onSuccess: (next) => {
      queryClient.setQueryData(schedule(), next);
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
      disabled={isDemo}
      error={patch.error}
      onSave={(body) => {
        if (!isDemo) patch.mutate(body);
      }}
    />
  );
}

interface ScheduleFormProps {
  readonly schedule: Schedule;
  readonly pending: boolean;
  readonly disabled: boolean;
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
  const { schedule, pending, disabled, error, onSave } = props;
  const [frequency, setFrequency] = useState<ScheduleFrequency>(schedule.schedule_frequency);
  const [times, setTimes] = useState<string[]>([...schedule.schedule_times_local]);
  const [timezone, setTimezone] = useState<string>(schedule.schedule_timezone);
  const timezoneOptions = buildTimezoneOptions(timezone);
  const nextRun = schedule.next_run_at_utc ? new Date(schedule.next_run_at_utc) : null;

  const onFrequencyChange = (next: ScheduleFrequency): void => {
    if (disabled) return;
    const required = FREQUENCY_OPTIONS.find((option) => option.value === next)?.slots ?? 0;
    const nextTimes = padSlots(times, required);
    setFrequency(next);
    setTimes(nextTimes);
    onSave({ schedule_frequency: next, schedule_times_local: nextTimes });
  };

  const onTimeChange = (index: number, next: string): void => {
    if (disabled) return;
    const nextTimes = [...times];
    nextTimes[index] = next;
    setTimes(nextTimes);
    onSave({ schedule_times_local: nextTimes });
  };

  const onTimezoneChange = (next: string): void => {
    if (disabled) return;
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
                  disabled={disabled || pending}
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
                    disabled={disabled || pending}
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
              disabled={disabled || pending}
              onChange={(event) => onTimezoneChange(event.target.value)}
              className={`${FORM_CONTROL_CLASS} w-full`}
            >
              {timezoneOptions.map((zone) => (
                <option key={zone.value} value={zone.value}>
                  {zone.label}
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
            disabled={disabled || pending}
            title={disabled ? 'Disabled in demo' : undefined}
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
 * Build the timezone dropdown options, restricted to US + India zones.
 *
 * The currently stored zone is always included so the controlled select
 * still reflects a value that pre-dates this restriction (e.g. a legacy
 * `UTC` setting) rather than silently snapping to another zone.
 *
 * @param current - The schedule's currently stored IANA timezone.
 * @returns Ordered option descriptors for the timezone select.
 */
function buildTimezoneOptions(current: string): ReadonlyArray<TimezoneOption> {
  if (US_INDIA_TIMEZONES.some((zone) => zone.value === current)) {
    return US_INDIA_TIMEZONES;
  }
  return [{ value: current, label: current }, ...US_INDIA_TIMEZONES];
}
