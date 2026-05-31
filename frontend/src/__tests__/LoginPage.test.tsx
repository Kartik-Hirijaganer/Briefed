import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import LoginPage from '../pages/LoginPage';

const startMock = vi.hoisted(() => vi.fn());
const useAddGmailFlowMock = vi.hoisted(() =>
  vi.fn(() => ({
    start: startMock,
    startUrl: '/api/v1/oauth/gmail/start?return_to=%2F',
    opensInNewTab: false,
  })),
);

vi.mock('../hooks/useAddGmailFlow', () => ({
  useAddGmailFlow: useAddGmailFlowMock,
}));

describe('<LoginPage>', () => {
  beforeEach(() => {
    startMock.mockClear();
    useAddGmailFlowMock.mockClear();
  });

  it('renders the welcome card with read-only language', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole('heading', { level: 1, name: /welcome to briefed/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/read-only Gmail access/i)).toBeInTheDocument();
  });

  it('invokes useAddGmailFlow.start when continue is clicked', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /continue with google/i }));
    expect(startMock).toHaveBeenCalledTimes(1);
  });

  it('uses the login next parameter as the OAuth return path', () => {
    render(
      <MemoryRouter initialEntries={['/login?next=%2Fsettings%2Faccounts']}>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(useAddGmailFlowMock).toHaveBeenCalledWith({ returnTo: '/settings/accounts' });
  });

  it('falls back to the dashboard for unsafe next parameters', () => {
    render(
      <MemoryRouter initialEntries={['/login?next=%2F%2Fevil.example']}>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(useAddGmailFlowMock).toHaveBeenCalledWith({ returnTo: '/' });
  });
});
