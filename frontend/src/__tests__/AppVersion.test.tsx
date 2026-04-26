import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AppVersion } from '../components/AppVersion';

describe('<AppVersion>', () => {
  it('renders the build version with a leading "v"', () => {
    render(<AppVersion />);
    const span = screen.getByText(/^v\d+\.\d+\.\d+/);
    expect(span).toBeInTheDocument();
    expect(span.tagName).toBe('SPAN');
  });

  it('exposes an aria-label that mirrors the rendered version', () => {
    render(<AppVersion />);
    const matched = screen.getByLabelText(/^App version \d+\.\d+\.\d+/);
    expect(matched).toBeInTheDocument();
  });
});
