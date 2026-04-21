import { Button } from '@briefed/ui';

/**
 * 404 fallback under the `AppShell` outlet.
 *
 * @returns The rendered placeholder.
 */
export default function NotFoundPage(): JSX.Element {
  return (
    <section className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <h1 className="text-3xl font-semibold">404</h1>
      <p className="text-sm text-fg-muted">This page is not in the release 1.0.0 plan.</p>
      <Button variant="link" href="/">
        Back to dashboard
      </Button>
    </section>
  );
}
