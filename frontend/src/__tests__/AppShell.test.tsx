import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { AppShell } from '../shell/AppShell';

vi.mock('../features/offline/OfflineBanners', () => ({
  OfflineBanners: () => <div data-testid="offline-banners" />,
}));
vi.mock('../features/offline/QueuedActionsSheet', () => ({
  QueuedActionsSheet: () => <div data-testid="queued-actions" />,
}));
vi.mock('../components/AppVersion', () => ({
  AppVersion: () => <span data-testid="app-version">v</span>,
}));

const wrap = (initial: string): JSX.Element => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div data-testid="page">home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe('<AppShell>', () => {
  it('renders sidebar, bottom tab bar, version, offline banners and outlet content', () => {
    render(wrap('/'));
    expect(screen.getByText('Briefed')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: /primary mobile/i })).toBeInTheDocument();
    expect(screen.getByTestId('offline-banners')).toBeInTheDocument();
    expect(screen.getByTestId('queued-actions')).toBeInTheDocument();
    expect(screen.getByTestId('app-version')).toBeInTheDocument();
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });
});
