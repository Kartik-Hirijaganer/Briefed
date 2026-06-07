import type { DecisionSource } from './WhyBadge';

const SOURCE_LABEL: Record<DecisionSource, string> = {
  rule: 'Rule',
  llm: 'LLM',
  hybrid: 'Rule + LLM',
};

/**
 * Props for {@link WhySortedBanner}.
 */
export interface WhySortedBannerProps {
  /** Human label for the bucket this item landed in (e.g. "Must-Read"). */
  readonly bucketLabel: string;
  /** Ordered, human-readable reasons the pipeline produced. */
  readonly reasons: readonly string[];
  /** Source that produced the decision. */
  readonly decisionSource: DecisionSource;
  /** Confidence in the range [0, 1]. */
  readonly confidence: number;
  /** When true, the row was flagged low-confidence for human review. */
  readonly needsReview: boolean;
}

/**
 * Always-visible "why was this sorted here" banner shown at the top of the
 * reading pane. Unlike the click-to-expand {@link WhyBadge} (kept for table
 * rows), this surfaces the reasoning inline so the reader never has to ask.
 *
 * @param props - Component props.
 * @returns The rendered banner.
 */
export function WhySortedBanner(props: WhySortedBannerProps): JSX.Element {
  const { bucketLabel, reasons, decisionSource, confidence, needsReview } = props;
  const confidencePct = Math.round(confidence * 100);
  const lead = `Marked ${bucketLabel} — ${reasons.join(' ')}`;
  return (
    <div className="flex flex-col gap-1 rounded-[var(--radius-md)] border border-accent/30 bg-accent/10 p-3 text-sm text-accent">
      <p>
        {lead}
        {needsReview ? ' …double-check before acting.' : ''}
      </p>
      <p className="text-xs text-accent/80">
        {SOURCE_LABEL[decisionSource]} · {confidencePct}% confidence
      </p>
    </div>
  );
}
