import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BriefedMark, BriefedWordmark } from '../components/brand/BriefedLogo';

describe('BriefedLogo', () => {
  it('renders the mark as decorative by default', () => {
    const { container } = render(<BriefedMark size={24} />);
    const svg = container.querySelector('svg');

    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg).toHaveAttribute('width', '24');
    expect(container.querySelectorAll('rect')).toHaveLength(4);
  });

  it('renders an accessible mark when a title is provided', () => {
    render(<BriefedMark title="Briefed mark" />);

    expect(screen.getByRole('img', { name: /briefed mark/i })).toBeInTheDocument();
  });

  it('renders the wordmark with the product name', () => {
    render(<BriefedWordmark size={32} />);

    expect(screen.getByLabelText('Briefed')).toBeInTheDocument();
    expect(screen.getByText('Briefed')).toBeInTheDocument();
  });
});
