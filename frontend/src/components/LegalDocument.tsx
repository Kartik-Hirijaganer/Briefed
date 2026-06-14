import { Link } from 'react-router-dom';

import { BriefedWordmark } from './brand/BriefedLogo';
import type { LegalContent } from '../content/legal';

/**
 * Props for the structured legal document renderer.
 */
export interface LegalDocumentProps {
  /** Structured content to render. */
  readonly content: LegalContent;
}

/**
 * Props for the public legal page layout.
 */
export interface LegalPageLayoutProps {
  /** Structured content to render inside the public chrome. */
  readonly content: LegalContent;
}

/**
 * Render a structured legal document with native headings and paragraphs.
 *
 * @param props - Component props.
 * @param props.content - Structured content to render.
 * @returns The rendered legal article.
 */
export function LegalDocument(props: LegalDocumentProps): JSX.Element {
  const { content } = props;
  const hasMeta = content.version !== undefined || content.effectiveDate !== undefined;

  return (
    <article className="mx-auto flex w-full max-w-[var(--measure)] flex-col gap-[var(--space-8)] py-[var(--space-12)]">
      <header className="flex flex-col gap-[var(--space-3)]">
        {hasMeta ? (
          <p className="font-mono text-[length:var(--fs-xs)] leading-[var(--lh-xs)] text-fg-faint">
            {content.version !== undefined ? `Version ${content.version}` : null}
            {content.version !== undefined && content.effectiveDate !== undefined ? ' | ' : null}
            {content.effectiveDate !== undefined ? `Effective ${content.effectiveDate}` : null}
          </p>
        ) : null}
        <h1 className="font-display text-[length:var(--fs-3xl)] font-semibold leading-[var(--lh-3xl)] tracking-[var(--tracking-tighter)] text-fg">
          {content.title}
        </h1>
        {content.intro.map((paragraph) => (
          <p key={paragraph} className="text-[length:var(--fs-base)] leading-[var(--lh-base)]">
            {paragraph}
          </p>
        ))}
      </header>

      {content.sections.map((section) => (
        <section key={section.id} id={section.id} className="flex flex-col gap-[var(--space-3)]">
          <h2 className="font-display text-[length:var(--fs-xl)] font-semibold leading-[var(--lh-xl)] tracking-[var(--tracking-tight)] text-fg">
            {section.title}
          </h2>
          {section.paragraphs.map((paragraph) => (
            <p
              key={paragraph}
              className="text-[length:var(--fs-base)] leading-[var(--lh-base)] text-fg-muted"
            >
              {paragraph}
            </p>
          ))}
        </section>
      ))}
    </article>
  );
}

/**
 * Render the public page chrome around a legal or about document.
 *
 * @param props - Component props.
 * @param props.content - Structured content to render.
 * @returns The public content page.
 */
export function LegalPageLayout(props: LegalPageLayoutProps): JSX.Element {
  const { content } = props;

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
            <Link className="text-link hover:text-accent" to="/login">
              Connect Gmail
            </Link>
          </nav>
        </div>
      </header>
      <div className="px-[var(--space-4)] md:px-[var(--space-8)]">
        <LegalDocument content={content} />
      </div>
      <footer className="border-t border-border bg-bg-muted px-[var(--space-4)] py-[var(--space-6)] md:px-[var(--space-8)]">
        <div className="mx-auto flex w-full max-w-[var(--measure)] flex-wrap items-center gap-[var(--space-4)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
          <span>Briefed is not for HIPAA-regulated healthcare data.</span>
          <Link className="text-link hover:text-accent" to="/privacy">
            Privacy
          </Link>
          <Link className="text-link hover:text-accent" to="/terms">
            Terms
          </Link>
        </div>
      </footer>
    </main>
  );
}
