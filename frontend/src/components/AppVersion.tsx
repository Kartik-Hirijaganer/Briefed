/**
 * App-version pill (Track C — Phase I.8).
 *
 * Renders the bundle's `__APP_VERSION__` string in a monospace span.
 * Sourced from `packages/contracts/version.json` via Vite's `define`
 * — kept identical to the backend OpenAPI `info.version` and the
 * `release_metadata.api_schema_version` ledger column.
 */

import type { ReactNode } from 'react';

interface AppVersionProps {
  /** Optional class additions appended after the base styling. */
  readonly className?: string;
}

/**
 * Render the current build version as `vX.Y.Z`.
 *
 * @param props - Optional class overrides.
 * @returns The version pill.
 */
export function AppVersion(props: AppVersionProps): ReactNode {
  const className = ['font-mono text-xs text-fg-muted', props.className ?? '']
    .filter(Boolean)
    .join(' ');
  return (
    <span className={className} aria-label={`App version ${__APP_VERSION__}`}>
      v{__APP_VERSION__}
    </span>
  );
}
