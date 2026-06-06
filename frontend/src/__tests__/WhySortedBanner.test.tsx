import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { WhySortedBanner } from '@briefed/ui';

describe('<WhySortedBanner>', () => {
  it('renders the marked-bucket lead with joined reasons and the source line', () => {
    render(
      <WhySortedBanner
        bucketLabel="Must-Read"
        reasons={['Sender is on your VIP rules.', 'Mentions a deadline.']}
        decisionSource="rule"
        confidence={0.91}
        needsReview={false}
      />,
    );
    expect(
      screen.getByText(/Marked Must-Read — Sender is on your VIP rules\. Mentions a deadline\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/Rule · 91% confidence/)).toBeInTheDocument();
  });

  it('does not append the review caveat when needsReview is false', () => {
    render(
      <WhySortedBanner
        bucketLabel="Good-to-Read"
        reasons={['Newsletter you read often.']}
        decisionSource="llm"
        confidence={0.6}
        needsReview={false}
      />,
    );
    expect(screen.queryByText(/double-check before acting/i)).not.toBeInTheDocument();
  });

  it('appends the review caveat when needsReview is true', () => {
    render(
      <WhySortedBanner
        bucketLabel="Ignore"
        reasons={['Low engagement sender.']}
        decisionSource="hybrid"
        confidence={0.42}
        needsReview
      />,
    );
    expect(screen.getByText(/double-check before acting\./i)).toBeInTheDocument();
    expect(screen.getByText(/Rule \+ LLM · 42% confidence/)).toBeInTheDocument();
  });
});
