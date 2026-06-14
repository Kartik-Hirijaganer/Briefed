import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import AboutPage from '../pages/AboutPage';
import PrivacyPolicyPage from '../pages/PrivacyPolicyPage';
import TermsOfServicePage from '../pages/TermsOfServicePage';

const renderPage = (page: JSX.Element): void => {
  render(<MemoryRouter>{page}</MemoryRouter>);
};

const PUBLIC_PAGE_CASES: ReadonlyArray<[string, () => JSX.Element]> = [
  ['privacy policy', () => <PrivacyPolicyPage />],
  ['terms of service', () => <TermsOfServicePage />],
  ['about page', () => <AboutPage />],
];

describe('public legal pages', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the privacy policy with Limited Use and exact LLM routing language', () => {
    renderPage(<PrivacyPolicyPage />);

    expect(screen.getByRole('heading', { level: 1, name: /privacy policy/i })).toBeInTheDocument();
    expect(screen.getByText(/Limited Use requirements/i)).toBeInTheDocument();
    expect(screen.getByText(/Google Gemini 2\.5 Flash/i)).toBeInTheDocument();
    expect(screen.getByText(/Anthropic Claude Haiku 4\.5/i)).toBeInTheDocument();
    expect(
      screen.getByText(/does not guarantee that all personal information/i),
    ).toBeInTheDocument();
  });

  it('renders terms with AI, HIPAA, Google API, and governing-law terms', () => {
    renderPage(<TermsOfServicePage />);

    expect(
      screen.getByRole('heading', { level: 1, name: /terms of service/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/AI output can be incomplete/i)).toBeInTheDocument();
    expect(screen.getByText(/HIPAA-regulated healthcare workflows/i)).toBeInTheDocument();
    expect(screen.getByText(/Google API terms/i)).toBeInTheDocument();
    expect(screen.getByText(/Maryland law and applicable U\.S\. federal law/i)).toBeInTheDocument();
  });

  it('renders about content with synthetic demo and real Gmail path distinction', () => {
    renderPage(<AboutPage />);

    expect(screen.getByRole('heading', { level: 1, name: /about briefed/i })).toBeInTheDocument();
    expect(screen.getByText(/synthetic inbox data/i)).toBeInTheDocument();
    expect(screen.getByText(/real Gmail path/i)).toBeInTheDocument();
  });

  it.each(PUBLIC_PAGE_CASES)('uses public chrome links and no API calls on %s', (_label, page) => {
    const apiGetSpy = vi.spyOn(api, 'GET');
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    renderPage(page());

    const navigation = screen.getByRole('navigation', { name: /public pages/i });
    expect(within(navigation).getByRole('link', { name: /about/i })).toHaveAttribute(
      'href',
      '/about',
    );
    expect(within(navigation).getByRole('link', { name: /privacy/i })).toHaveAttribute(
      'href',
      '/privacy',
    );
    expect(within(navigation).getByRole('link', { name: /terms/i })).toHaveAttribute(
      'href',
      '/terms',
    );
    expect(apiGetSpy).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    for (const link of screen.getAllByRole('link')) {
      expect(link.getAttribute('href') ?? '').not.toMatch(/^\/api\//);
    }
  });
});
