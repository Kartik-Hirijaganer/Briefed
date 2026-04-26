/**
 * Profile + schedule + appearance + privacy panels (Track C — Phase II.6).
 *
 * Renders four cards on the settings landing page:
 *   1. Profile — display name, email aliases, redaction aliases.
 *   2. Schedule — cadence radio, time slots, timezone, next-run preview.
 *   3. Appearance — `<ThemeToggle>` from Group I.
 *   4. Privacy — Presidio toggle.
 *
 * Each section invalidates the relevant React Query cache on mutation.
 * The hook also calls `useTheme().hydrateFromProfile` once the profile
 * row arrives so the server preference wins after auth.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

// Import primitives by file rather than via the @briefed/ui barrel —
// the barrel re-exports SafeMarkdown which transitively imports
// react-markdown. The test environment in this checkout does not
// always have that optional runtime dep installed, so direct imports
// keep these settings panels test-friendly.
import { Card } from '../../../../packages/ui/src/primitives/Card';
import { ErrorState } from '../../../../packages/ui/src/primitives/ErrorState';
import { Field } from '../../../../packages/ui/src/primitives/Field';
import { Skeleton } from '../../../../packages/ui/src/primitives/Skeleton';
import { Switch } from '../../../../packages/ui/src/primitives/Switch';

import { ThemeToggle } from '../../components/ThemeToggle';
import { useTheme } from '../../hooks/useTheme';

import {
  fetchProfile,
  fetchSchedule,
  patchProfile,
  patchSchedule,
  type ScheduleFrequency,
  type UserProfile,
  type UserSchedule,
} from './profileApi';

const FREQUENCY_OPTIONS: ReadonlyArray<{ value: ScheduleFrequency; label: string; slots: number }> =
  [
    { value: 'once_daily', label: 'Once a day', slots: 1 },
    { value: 'twice_daily', label: 'Twice a day', slots: 2 },
    { value: 'disabled', label: 'Disabled', slots: 0 },
  ];

/**
 * Pad a candidate slot value out to exactly the required slot count.
 *
 * @param slots - Existing time strings.
 * @param required - Number of slots the new cadence requires.
 * @returns A new tuple of `required` items, padded with `'08:00'` /
 *   `'18:00'` defaults so the cadence-consistency invariant holds.
 */
function padSlots(slots: readonly string[], required: number): string[] {
  const out = [...slots];
  if (required === 0) return [];
  const defaults = ['08:00', '18:00'];
  while (out.length < required) out.push(defaults[out.length] ?? '12:00');
  return out.slice(0, required);
}

/**
 * Compute the IANA timezone list once. Browsers expose this via
 * `Intl.supportedValuesOf('timeZone')` (Chromium / Firefox / Safari 16+).
 *
 * @returns A sorted list of timezone names.
 */
function listTimezones(): string[] {
  const supported =
    typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
  if (!supported.length) {
    return ['UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London'];
  }
  return [...supported].sort();
}

/**
 * Render the four Track C settings panels.
 *
 * @returns The rendered settings UI.
 */
export function ProfileSettings(): JSX.Element {
  const queryClient = useQueryClient();
  const { hydrateFromProfile } = useTheme();
  const profileQuery = useQuery({ queryKey: ['profile'], queryFn: fetchProfile });
  const scheduleQuery = useQuery({ queryKey: ['profile', 'schedule'], queryFn: fetchSchedule });

  const profileMutation = useMutation({
    mutationFn: patchProfile,
    onSuccess: (next) => {
      queryClient.setQueryData(['profile'], next);
    },
  });

  const scheduleMutation = useMutation({
    mutationFn: patchSchedule,
    onSuccess: (next) => {
      queryClient.setQueryData(['profile', 'schedule'], next);
    },
  });

  const profile = profileQuery.data;

  // Once the server profile resolves, mirror its theme preference into
  // the local hook so cross-device theme sync works.
  useEffect(() => {
    if (profile) hydrateFromProfile(profile.theme_preference);
  }, [profile, hydrateFromProfile]);

  if (profileQuery.isPending || scheduleQuery.isPending) return <Skeleton shape="block" />;
  if (profileQuery.isError || !profileQuery.data) {
    return (
      <ErrorState
        title="Could not load profile"
        detail={profileQuery.error instanceof Error ? profileQuery.error.message : undefined}
      />
    );
  }
  if (scheduleQuery.isError || !scheduleQuery.data) {
    return (
      <ErrorState
        title="Could not load schedule"
        detail={scheduleQuery.error instanceof Error ? scheduleQuery.error.message : undefined}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <ProfileCard profile={profileQuery.data} onSave={profileMutation.mutate} />
      <ScheduleCard schedule={scheduleQuery.data} onSave={scheduleMutation.mutate} />
      <AppearanceCard
        onPreferenceChange={(next) => profileMutation.mutate({ theme_preference: next })}
      />
      <PrivacyCard
        profile={profileQuery.data}
        onToggle={(next) => profileMutation.mutate({ presidio_enabled: next })}
      />
    </div>
  );
}

interface ProfileCardProps {
  readonly profile: UserProfile;
  readonly onSave: (body: {
    display_name?: string | null;
    email_aliases?: readonly string[];
    redaction_aliases?: readonly string[];
  }) => void;
}

/**
 * Profile card — display name + alias inputs.
 *
 * @param props - Component props.
 * @returns The rendered card.
 */
function ProfileCard(props: ProfileCardProps): JSX.Element {
  const [displayName, setDisplayName] = useState<string>(props.profile.display_name ?? '');
  const [emailAliases, setEmailAliases] = useState<string>(props.profile.email_aliases.join(', '));
  const [redactionAliases, setRedactionAliases] = useState<string>(
    props.profile.redaction_aliases.join(', '),
  );

  /**
   * Persist the form values, splitting comma-separated alias lists
   * into trimmed, deduplicated arrays.
   */
  const save = (): void => {
    const split = (raw: string): string[] =>
      Array.from(
        new Set(
          raw
            .split(/[,\n]/)
            .map((item) => item.trim())
            .filter((item) => item.length > 0),
        ),
      );
    props.onSave({
      display_name: displayName.trim() ? displayName.trim() : null,
      email_aliases: split(emailAliases),
      redaction_aliases: split(redactionAliases),
    });
  };

  return (
    <Card className="flex flex-col gap-4">
      <header>
        <h2 className="text-base font-semibold text-fg">Profile</h2>
        <p className="text-sm text-fg-muted">
          Briefed scrubs these values from prompts before they reach the LLM.
        </p>
      </header>
      <Field label="Display name">
        <input
          id="profile-display-name"
          type="text"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          onBlur={save}
          className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
        />
      </Field>
      <Field
        label="Email aliases"
        description="Comma-separated. Each entry is removed from prompts."
      >
        <input
          id="profile-email-aliases"
          type="text"
          value={emailAliases}
          onChange={(event) => setEmailAliases(event.target.value)}
          onBlur={save}
          placeholder="alt@example.com, work@example.com"
          className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
        />
      </Field>
      <Field
        label="Redaction aliases"
        description="Comma-separated free-form strings; useful for nicknames or company codenames."
      >
        <input
          id="profile-redaction-aliases"
          type="text"
          value={redactionAliases}
          onChange={(event) => setRedactionAliases(event.target.value)}
          onBlur={save}
          className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
        />
      </Field>
    </Card>
  );
}

interface ScheduleCardProps {
  readonly schedule: UserSchedule;
  readonly onSave: (body: {
    schedule_frequency?: ScheduleFrequency;
    schedule_times_local?: readonly string[];
    schedule_timezone?: string;
  }) => void;
}

/**
 * Schedule card — cadence, time pickers, timezone, next-run preview.
 *
 * @param props - Component props.
 * @returns The rendered card.
 */
function ScheduleCard(props: ScheduleCardProps): JSX.Element {
  const [frequency, setFrequency] = useState<ScheduleFrequency>(props.schedule.schedule_frequency);
  const [times, setTimes] = useState<string[]>([...props.schedule.schedule_times_local]);
  const [timezone, setTimezone] = useState<string>(props.schedule.schedule_timezone);
  const timezones = useMemo(listTimezones, []);

  const onFrequencyChange = (next: ScheduleFrequency): void => {
    const required = FREQUENCY_OPTIONS.find((opt) => opt.value === next)?.slots ?? 0;
    const padded = padSlots(times, required);
    setFrequency(next);
    setTimes(padded);
    props.onSave({ schedule_frequency: next, schedule_times_local: padded });
  };

  const onTimeChange = (index: number, next: string): void => {
    const updated = [...times];
    updated[index] = next;
    setTimes(updated);
    props.onSave({ schedule_times_local: updated });
  };

  const onTimezoneChange = (next: string): void => {
    setTimezone(next);
    props.onSave({ schedule_timezone: next });
  };

  const nextRun = props.schedule.next_run_at_utc ? new Date(props.schedule.next_run_at_utc) : null;

  return (
    <Card className="flex flex-col gap-4">
      <header>
        <h2 className="text-base font-semibold text-fg">Schedule</h2>
        <p className="text-sm text-fg-muted">
          When Briefed scans your inbox automatically. The next run preview is computed by the same
          predicate the server uses to fan out work.
        </p>
      </header>
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-fg">Cadence</legend>
        {FREQUENCY_OPTIONS.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm text-fg">
            <input
              type="radio"
              name="schedule-frequency"
              checked={frequency === option.value}
              onChange={() => onFrequencyChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      {frequency !== 'disabled' ? (
        <Field label="Time slots (local)">
          <div className="flex flex-wrap gap-2">
            {times.map((time, index) => (
              <input
                key={index}
                id={`schedule-time-${index}`}
                type="time"
                value={time}
                onChange={(event) => onTimeChange(index, event.target.value)}
                className="h-10 rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
              />
            ))}
          </div>
        </Field>
      ) : null}
      <Field label="Timezone">
        <select
          id="schedule-timezone"
          value={timezone}
          onChange={(event) => onTimezoneChange(event.target.value)}
          className="h-10 w-full rounded-[var(--radius-md)] border border-border-strong bg-bg-surface px-3 text-sm"
        >
          {timezones.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
      </Field>
      <p className="text-xs text-fg-muted">
        Next run: <span className="font-mono">{nextRun ? nextRun.toLocaleString() : '—'}</span>
      </p>
    </Card>
  );
}

interface AppearanceCardProps {
  readonly onPreferenceChange: (next: 'system' | 'light' | 'dark') => void;
}

/**
 * Appearance card wrapping `<ThemeToggle>`. Forwards the user's pick
 * to the profile mutation so `users.theme_preference` stays in sync
 * across devices.
 *
 * @param props - Component props.
 * @returns The rendered card.
 */
function AppearanceCard(props: AppearanceCardProps): JSX.Element {
  return (
    <Card className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold text-fg">Appearance</h2>
        <p className="text-sm text-fg-muted">
          Choose how Briefed paints the canvas. System tracks your OS preference.
        </p>
      </header>
      <ThemeToggle onChange={props.onPreferenceChange} />
    </Card>
  );
}

interface PrivacyCardProps {
  readonly profile: UserProfile;
  readonly onToggle: (next: boolean) => void;
}

/**
 * Privacy card — Presidio toggle.
 *
 * @param props - Component props (current profile + toggle handler).
 * @returns The privacy card section.
 */
function PrivacyCard(props: PrivacyCardProps): JSX.Element {
  return (
    <Card className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold text-fg">Privacy</h2>
        <p className="text-sm text-fg-muted">
          Run the Microsoft Presidio entity scrubber ahead of regex / alias redaction.
        </p>
      </header>
      <Field label="Presidio enabled">
        <Switch
          checked={props.profile.presidio_enabled}
          onCheckedChange={props.onToggle}
          ariaLabel="Run Presidio entity scrubber"
        />
      </Field>
    </Card>
  );
}
