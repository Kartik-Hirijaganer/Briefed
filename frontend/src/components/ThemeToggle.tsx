/**
 * Three-state theme toggle (Track C — Phase I.7).
 *
 * Segmented control rendered in Settings → Appearance and (compactly)
 * in the user menu. Wires the `useTheme` preference into the optional
 * profile mutation so the server-side `theme_preference` stays in sync
 * once authentication has resolved.
 */

import type { ReactNode } from 'react';

import { useTheme, type ThemePreference } from '../hooks/useTheme';

interface ThemeOption {
  readonly value: ThemePreference;
  readonly label: string;
}

const OPTIONS: readonly ThemeOption[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

interface ThemeToggleProps {
  /** Optional callback invoked whenever the user picks a new preference. */
  readonly onChange?: (next: ThemePreference) => void;
  /** Optional class additions; the segmented base styling is built-in. */
  readonly className?: string;
  /** Optional `aria-label` override for screen readers. */
  readonly ariaLabel?: string;
}

/**
 * Render a System / Light / Dark segmented control bound to `useTheme`.
 *
 * @param props - Optional change handler + class/label overrides.
 * @returns The rendered segmented control.
 */
export function ThemeToggle(props: ThemeToggleProps): ReactNode {
  const { preference, setPreference } = useTheme();
  const className = [
    'inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-border bg-bg-surface p-1',
    props.className ?? '',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div role="radiogroup" aria-label={props.ariaLabel ?? 'Theme'} className={className}>
      {OPTIONS.map((option) => {
        const active = preference === option.value;
        const optionClass = [
          'rounded-[var(--radius-sm)] px-3 py-1 text-xs font-medium transition-colors',
          active ? 'bg-accent text-fg-on-accent' : 'text-fg-muted hover:text-fg',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2',
        ].join(' ');
        return (
          <button
            type="button"
            key={option.value}
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            className={optionClass}
            onClick={() => {
              if (active) return;
              setPreference(option.value);
              props.onChange?.(option.value);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
