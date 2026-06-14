import { Card } from '@briefed/ui';
import { Link } from 'react-router-dom';

import { BriefedWordmark } from '../components/brand/BriefedLogo';

const FEATURE_CARDS = [
  {
    title: 'Rank the inbox',
    body: 'Briefed sorts Gmail into priority lanes so must-read messages, replies, and waiting threads are easy to scan.',
  },
  {
    title: 'Summarize context',
    body: 'Daily briefs compress long threads into decisions, blockers, deadlines, and follow-up work.',
  },
  {
    title: 'Spot inbox hygiene',
    body: 'Newsletter and sender views surface patterns that make cleanup decisions faster and less repetitive.',
  },
] as const;

const TRUST_NOTES = [
  'Read-only-first Gmail access',
  'Not for HIPAA-regulated healthcare data',
  'Demo uses synthetic data only',
] as const;

const PRIMARY_CTA_CLASS =
  'inline-flex min-h-[var(--control-height)] items-center justify-center rounded-[var(--radius-md)] ' +
  'bg-accent px-[var(--space-6)] py-[var(--space-3)] text-[length:var(--fs-base)] ' +
  'font-medium leading-[var(--lh-base)] text-fg-on-accent transition-colors ' +
  'duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:bg-accent-hover ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] ' +
  'focus-visible:ring-offset-2';

const SECONDARY_CTA_CLASS =
  'inline-flex min-h-[var(--control-height)] items-center justify-center rounded-[var(--radius-md)] ' +
  'border border-border-strong bg-transparent px-[var(--space-6)] py-[var(--space-3)] ' +
  'text-[length:var(--fs-base)] font-medium leading-[var(--lh-base)] text-fg transition-colors ' +
  'duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:bg-bg-muted ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] ' +
  'focus-visible:ring-offset-2';

const isGmailConnectEnabled = (): boolean => import.meta.env.VITE_ENABLE_GMAIL_CONNECT === 'true';

/**
 * Public marketing homepage. Makes no authenticated API calls.
 *
 * @returns The rendered public homepage.
 */
export default function HomePage(): JSX.Element {
  const gmailConnectEnabled = isGmailConnectEnabled();

  return (
    <main className="min-h-[100dvh] bg-bg-canvas text-fg">
      <header className="border-b border-border bg-bg-canvas">
        <div className="mx-auto flex w-full max-w-[var(--container-wide)] flex-col gap-[var(--space-4)] px-[var(--space-4)] py-[var(--space-4)] md:flex-row md:items-center md:justify-between md:px-[var(--space-8)]">
          <Link to="/" aria-label="Briefed home" className="w-fit">
            <BriefedWordmark size={28} />
          </Link>
          <nav
            aria-label="Public pages"
            className="flex flex-wrap items-center gap-[var(--space-4)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)]"
          >
            <Link className="text-link hover:text-accent" to="/about">
              About
            </Link>
            <Link className="text-link hover:text-accent" to="/privacy">
              Privacy
            </Link>
            <Link className="text-link hover:text-accent" to="/terms">
              Terms
            </Link>
          </nav>
        </div>
      </header>

      <section className="mx-auto flex w-full max-w-[var(--container-wide)] flex-col gap-[var(--space-8)] px-[var(--space-4)] py-[var(--space-12)] md:px-[var(--space-8)] md:py-[var(--space-16)]">
        <div className="flex max-w-[var(--measure)] flex-col gap-[var(--space-4)]">
          <BriefedWordmark size={36} />
          <div className="flex flex-col gap-[var(--space-3)]">
            <h1 className="font-display text-[length:var(--fs-3xl)] font-semibold leading-[var(--lh-3xl)] tracking-[var(--tracking-tighter)] text-fg">
              Briefed
            </h1>
            <p className="text-[length:var(--fs-lg)] leading-[var(--lh-lg)] text-fg-muted">
              AI inbox triage for Gmail. Preview it with demo data, or connect your own mailbox when
              you're ready.
            </p>
          </div>
        </div>

        <div className="grid gap-[var(--space-4)] md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="flex flex-col items-start gap-[var(--space-2)]">
            <Link to="/demo" className={PRIMARY_CTA_CLASS}>
              Try Demo
            </Link>
            <p className="max-w-[var(--measure)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
              Explore Briefed with synthetic inbox data. No Google account required.
            </p>
          </div>
          {gmailConnectEnabled ? (
            <div className="flex flex-col items-start gap-[var(--space-2)]">
              <Link to="/login" className={SECONDARY_CTA_CLASS}>
                Connect Gmail
              </Link>
              <p className="max-w-[var(--measure)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
                Connect your own mailbox after reviewing the policies.
              </p>
            </div>
          ) : null}
        </div>
      </section>

      <section
        aria-labelledby="what-it-does"
        className="border-y border-border bg-bg-muted px-[var(--space-4)] py-[var(--space-12)] md:px-[var(--space-8)]"
      >
        <div className="mx-auto flex w-full max-w-[var(--container-wide)] flex-col gap-[var(--space-6)]">
          <h2
            id="what-it-does"
            className="font-display text-[length:var(--fs-2xl)] font-semibold leading-[var(--lh-2xl)] tracking-[var(--tracking-tight)] text-fg"
          >
            What it does
          </h2>
          <div className="grid gap-[var(--space-4)] md:grid-cols-3">
            {FEATURE_CARDS.map((feature) => (
              <Card key={feature.title} className="flex flex-col gap-[var(--space-3)]">
                <h3 className="font-display text-[length:var(--fs-lg)] font-semibold leading-[var(--lh-lg)] text-fg">
                  {feature.title}
                </h3>
                <p className="text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
                  {feature.body}
                </p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto flex w-full max-w-[var(--container-wide)] flex-col gap-[var(--space-4)] px-[var(--space-4)] py-[var(--space-8)] md:px-[var(--space-8)]">
        <h2 className="font-display text-[length:var(--fs-xl)] font-semibold leading-[var(--lh-xl)] tracking-[var(--tracking-tight)] text-fg">
          Trust notes
        </h2>
        <ul className="flex flex-wrap gap-[var(--space-2)]">
          {TRUST_NOTES.map((note) => (
            <li
              key={note}
              className="rounded-[var(--radius-full)] border border-border bg-bg-surface px-[var(--space-3)] py-[var(--space-2)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted"
            >
              {note}
            </li>
          ))}
        </ul>
      </section>

      <footer className="border-t border-border bg-bg-canvas px-[var(--space-4)] py-[var(--space-6)] md:px-[var(--space-8)]">
        <div className="mx-auto flex w-full max-w-[var(--container-wide)] flex-wrap items-center gap-[var(--space-4)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
          <span>Briefed</span>
          <Link className="text-link hover:text-accent" to="/privacy">
            Privacy
          </Link>
          <Link className="text-link hover:text-accent" to="/terms">
            Terms
          </Link>
          <Link className="text-link hover:text-accent" to="/about">
            About
          </Link>
        </div>
      </footer>
    </main>
  );
}
