import { useState } from 'react';

import { Badge } from './Badge';

/**
 * A classification decision source — plan §19.7, surfaced per row.
 */
export type DecisionSource = 'rule' | 'llm' | 'hybrid';

/**
 * Props for {@link WhyBadge}.
 */
export interface WhyBadgeProps {
  /** Ordered list of human-readable reasons. */
  readonly reasons: readonly string[];
  /** Source that produced the decision. */
  readonly decisionSource: DecisionSource;
  /** Confidence in the range [0, 1]. */
  readonly confidence: number;
}

const SOURCE_LABEL: Record<DecisionSource, string> = {
  rule: 'Rule',
  llm: 'LLM',
  hybrid: 'Rule + LLM',
};

/**
 * Click-to-expand explainer attached to every email row. Exposes the
 * reason chain + decision source + confidence the pipeline computed —
 * enforced by lint on all feature rows per plan §19.8.
 *
 * @param props - Component props.
 * @returns The rendered badge + popover.
 */
export function WhyBadge(props: WhyBadgeProps): JSX.Element {
  const { reasons, decisionSource, confidence } = props;
  const [open, setOpen] = useState(false);
  const confidencePct = Math.round(confidence * 100);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-label="Why is this email here?"
        className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] rounded-full"
      >
        <Badge tone="accent">Why?</Badge>
      </button>
      {open ? (
        <div
          role="dialog"
          className="absolute right-0 top-6 z-10 w-72 rounded-[var(--radius-md)] border border-border bg-bg p-3 text-xs shadow-lg"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-fg">Classification</span>
            <span className="text-fg-muted">
              {SOURCE_LABEL[decisionSource]} · {confidencePct}%
            </span>
          </div>
          <ul className="list-disc pl-4 text-fg-muted">
            {reasons.map((reason, idx) => (
              <li key={`${idx}-${reason.slice(0, 16)}`}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </span>
  );
}
