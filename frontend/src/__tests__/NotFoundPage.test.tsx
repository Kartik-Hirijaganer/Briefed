import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import NotFoundPage from '../pages/NotFoundPage';

describe('<NotFoundPage>', () => {
  it('renders the 404 placeholder copy and a back link', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 1, name: '404' })).toBeInTheDocument();
    expect(screen.getByText(/not in the release 1.0.0 plan/i)).toBeInTheDocument();
    const back = screen.getByRole('link', { name: /back to dashboard/i });
    expect(back).toHaveAttribute('href', '/');
  });
});
