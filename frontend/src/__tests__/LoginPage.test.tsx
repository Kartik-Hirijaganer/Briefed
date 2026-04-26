import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import LoginPage from '../pages/LoginPage';

const startMock = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useAddGmailFlow', () => ({
  useAddGmailFlow: () => ({
    start: startMock,
    startUrl: '/api/v1/oauth/gmail/start?return_to=%2F',
    opensInNewTab: false,
  }),
}));

describe('<LoginPage>', () => {
  it('renders the welcome card with read-only language', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 1, name: /welcome to briefed/i })).toBeInTheDocument();
    expect(screen.getByText(/read-only Gmail access/i)).toBeInTheDocument();
  });

  it('invokes useAddGmailFlow.start when continue is clicked', async () => {
    startMock.mockClear();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /continue with google/i }));
    expect(startMock).toHaveBeenCalledTimes(1);
  });
});
