import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import HomePage from '../pages/HomePage';

const renderPage = (): void => {
  render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
};

describe('<HomePage>', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it('renders the public hero, demo CTA, feature cards, and trust notes', () => {
    renderPage();

    expect(screen.getByRole('heading', { level: 1, name: 'Briefed' })).toBeInTheDocument();
    expect(screen.getByText(/AI inbox triage for Gmail/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /try demo/i })).toHaveAttribute('href', '/demo');
    expect(screen.queryByRole('link', { name: /connect gmail/i })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: /what it does/i })).toBeInTheDocument();
    expect(screen.getByText(/Read-only-first Gmail access/i)).toBeInTheDocument();
    expect(screen.getByText(/Not for HIPAA-regulated healthcare data/i)).toBeInTheDocument();
    expect(screen.getByText(/Demo uses synthetic data only/i)).toBeInTheDocument();
  });

  it('routes the Connect Gmail CTA to login when the Gmail-connect flag is enabled', () => {
    vi.stubEnv('VITE_ENABLE_GMAIL_CONNECT', 'true');

    renderPage();

    expect(screen.getByRole('link', { name: /try demo/i })).toHaveAttribute('href', '/demo');
    expect(screen.getByRole('link', { name: /connect gmail/i })).toHaveAttribute('href', '/login');
    expect(screen.getByText(/after reviewing the policies/i)).toBeInTheDocument();
  });

  it('uses only public links and does not call authenticated APIs', () => {
    const apiGetSpy = vi.spyOn(api, 'GET');
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    renderPage();

    expect(screen.getAllByRole('link', { name: /privacy/i })[0]).toHaveAttribute(
      'href',
      '/privacy',
    );
    expect(screen.getAllByRole('link', { name: /terms/i })[0]).toHaveAttribute('href', '/terms');
    expect(screen.getAllByRole('link', { name: /about/i })[0]).toHaveAttribute('href', '/about');
    expect(apiGetSpy).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    for (const link of screen.getAllByRole('link')) {
      expect(link.getAttribute('href') ?? '').not.toMatch(/^\/api\//);
    }
  });
});
