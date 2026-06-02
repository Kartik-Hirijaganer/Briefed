import { render, screen } from '@testing-library/react';
import { TriangleAlert } from 'lucide-react';
import { describe, expect, it } from 'vitest';

import { ErrorState } from '@briefed/ui';

describe('<ErrorState>', () => {
  it('renders the title and no icon by default', () => {
    const { container } = render(<ErrorState title="Something failed" />);
    expect(screen.getByText('Something failed')).toBeInTheDocument();
    expect(container.querySelector('svg')).toBeNull();
  });

  it('renders a decorative lucide icon when one is provided', () => {
    const { container } = render(<ErrorState title="Rate limited" icon={TriangleAlert} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });
});
