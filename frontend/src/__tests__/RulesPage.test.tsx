import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import RulesPage from '../pages/settings/RulesPage';

const apiMock = vi.hoisted(() => ({
  DELETE: vi.fn(),
  GET: vi.fn(),
  POST: vi.fn(),
  PUT: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RulesPage />
    </QueryClientProvider>,
  );
};

describe('<RulesPage>', () => {
  beforeEach(() => {
    apiMock.DELETE.mockReset();
    apiMock.GET.mockReset();
    apiMock.POST.mockReset();
    apiMock.PUT.mockReset();
  });

  it('renders saved rules with friendly match and category labels', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        rules: [
          {
            id: 'r1',
            name: 'Manager',
            priority: 900,
            match: { from_domain: 'example.com' },
            action: { label: 'must_read', confidence: 0.95 },
            active: true,
            version: 1,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ],
      },
    });
    renderPage();

    expect(await screen.findByText('Manager')).toBeInTheDocument();
    expect(screen.getByText('Sender domain: example.com')).toBeInTheDocument();
    expect(screen.getAllByText('Must-Read').length).toBeGreaterThan(0);
    expect(screen.getByText('95% confidence')).toBeInTheDocument();
  });

  it('creates a sender-domain rule', async () => {
    const user = userEvent.setup();
    apiMock.GET.mockResolvedValue({ data: { rules: [] } });
    apiMock.POST.mockResolvedValue({
      data: {
        id: 'r2',
        name: 'Finance',
        priority: 500,
        match: { from_domain: 'finance.example' },
        action: { label: 'ignore', confidence: 0.8 },
        active: true,
        version: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    });
    renderPage();

    await user.type(await screen.findByLabelText(/name/i), 'Finance');
    await user.selectOptions(screen.getByLabelText(/match$/i), 'from_domain');
    await user.type(screen.getByLabelText(/match value/i), 'finance.example');
    await user.selectOptions(screen.getByLabelText(/category/i), 'ignore');
    await user.clear(screen.getByLabelText(/confidence/i));
    await user.type(screen.getByLabelText(/confidence/i), '0.8');
    await user.click(screen.getByRole('button', { name: /create rule/i }));

    await waitFor(() => expect(apiMock.POST).toHaveBeenCalled());
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/rubric', {
      body: {
        name: 'Finance',
        priority: 100,
        match: { from_domain: 'finance.example' },
        action: { label: 'ignore', confidence: 0.8 },
        active: true,
      },
    });
  });

  it('loads an existing rule into the editor and saves with PUT', async () => {
    const user = userEvent.setup();
    apiMock.GET.mockResolvedValue({
      data: {
        rules: [
          {
            id: 'r1',
            name: 'Security',
            priority: 700,
            match: { topic_keyword: ['security alert'] },
            action: { label: 'must_read', confidence: 0.9 },
            active: true,
            version: 1,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ],
      },
    });
    apiMock.PUT.mockResolvedValue({ data: {} });
    renderPage();

    await user.click(await screen.findByRole('button', { name: /edit/i }));
    await user.clear(screen.getByLabelText(/priority/i));
    await user.type(screen.getByLabelText(/priority/i), '750');
    await user.click(screen.getByRole('button', { name: /save rule/i }));

    await waitFor(() => expect(apiMock.PUT).toHaveBeenCalled());
    expect(apiMock.PUT).toHaveBeenCalledWith('/api/v1/rubric/{rule_id}', {
      params: { path: { rule_id: 'r1' } },
      body: {
        name: 'Security',
        priority: 750,
        match: { topic_keyword: ['security alert'] },
        action: { label: 'must_read', confidence: 0.9 },
        active: true,
      },
    });
  });

  it('deletes a rule', async () => {
    const user = userEvent.setup();
    apiMock.GET.mockResolvedValue({
      data: {
        rules: [
          {
            id: 'r1',
            name: 'Receipt',
            priority: 100,
            match: { subject_contains: 'receipt' },
            action: { label: 'ignore', confidence: 0.8 },
            active: true,
            version: 1,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ],
      },
    });
    apiMock.DELETE.mockResolvedValue({ response: { ok: true } });
    renderPage();

    await user.click(await screen.findByRole('button', { name: /delete/i }));
    await waitFor(() => expect(apiMock.DELETE).toHaveBeenCalled());
    expect(apiMock.DELETE).toHaveBeenCalledWith('/api/v1/rubric/{rule_id}', {
      params: { path: { rule_id: 'r1' } },
    });
  });
});
