import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { EmailCard } from '../features/email/EmailCard';

const baseEmail = {
  id: 'e1',
  account_email: 'me@example.com',
  thread_id: 't1',
  subject: 'Quarterly review tomorrow',
  sender: 'manager@example.com',
  bucket: 'must_read' as const,
  reasons: ['rubric'],
  decision_source: 'rubric',
  confidence: 0.92,
  summary_excerpt: 'Please confirm by 5pm.',
  received_at: '2026-04-25T10:00:00Z',
};

describe('<EmailCard>', () => {
  it('renders subject, sender, summary, and the why badge', () => {
    render(<EmailCard email={baseEmail} />);
    expect(screen.getByText('Quarterly review tomorrow')).toBeInTheDocument();
    expect(screen.getByText(/manager@example.com/)).toBeInTheDocument();
    expect(screen.getByText('Please confirm by 5pm.')).toBeInTheDocument();
  });

  it('renders the screen-reader move-to actions when onBucketChange is provided', () => {
    const onBucketChange = vi.fn();
    render(<EmailCard email={baseEmail} onBucketChange={onBucketChange} />);
    expect(screen.getByRole('button', { name: /move to must read/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /move to ignore/i })).toBeInTheDocument();
  });

  it('invokes onBucketChange when the move-to-ignore action fires', async () => {
    const onBucketChange = vi.fn();
    const user = userEvent.setup();
    render(<EmailCard email={baseEmail} onBucketChange={onBucketChange} />);
    await user.click(screen.getByRole('button', { name: /move to ignore/i }));
    expect(onBucketChange).toHaveBeenCalledWith(baseEmail, 'ignore');
  });

  it('skips firing onBucketChange when the bucket is unchanged', async () => {
    const onBucketChange = vi.fn();
    const user = userEvent.setup();
    render(<EmailCard email={baseEmail} onBucketChange={onBucketChange} />);
    await user.click(screen.getByRole('button', { name: /move to must read/i }));
    expect(onBucketChange).not.toHaveBeenCalled();
  });
});
